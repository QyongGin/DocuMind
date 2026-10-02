package com.documind.documind.global.infra.fastapi;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.core.io.Resource;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Component;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Flux;

import java.time.Duration;
import java.util.List;
import java.util.Objects;

// FastAPI 서버와 통신하는 HTTP 클라이언트
@Slf4j
// @Component: 스프링 빈으로 등록
@Component
public class FastApiClient {

    private final WebClient blockingWebClient;
    private final WebClient streamingWebClient;
    private final Duration responseTimeout;

    public FastApiClient(
            @Qualifier("fastApiBlockingWebClient") WebClient blockingWebClient,
            @Qualifier("fastApiStreamingWebClient") WebClient streamingWebClient,
            @Value("${fastapi.response-timeout:180s}") Duration responseTimeout
    ) {
        this.blockingWebClient = blockingWebClient;
        this.streamingWebClient = streamingWebClient;
        this.responseTimeout = responseTimeout;
    }

    // PDF 파일과 document_id를 FastAPI에 전송해 청킹·임베딩·저장을 요청
    public FastApiUploadResponse uploadDocument(MultipartFile file, Long documentId) {
        return uploadDocument(file, documentId, FastApiDocumentMetadata.EMPTY);
    }

    /**
     * 업로드 파일과 문서 메타데이터를 FastAPI에 전송해 청킹·임베딩·저장을 요청한다(동기 처리).
     *
     * @param file       업로드 파일
     * @param documentId MySQL documents PK
     * @param metadata   청크마다 넣을 문서 메타데이터
     * @return FastAPI 문서 처리 결과
     */
    public FastApiUploadResponse uploadDocument(MultipartFile file, Long documentId, FastApiDocumentMetadata metadata) {
        return uploadDocument(
                file.getResource(),
                Objects.requireNonNullElse(file.getOriginalFilename(), "upload"),
                documentId,
                metadata
        );
    }

    /**
     * 파일 Resource와 document_id를 FastAPI에 전송해 청킹·임베딩·저장을 요청한다.
     *
     * @param fileResource     FastAPI에 전달할 파일 Resource
     * @param originalFilename multipart filename으로 전달할 원본 파일명
     * @param documentId       MySQL documents PK
     * @return FastAPI 문서 처리 결과
     */
    public FastApiUploadResponse uploadDocument(Resource fileResource, String originalFilename, Long documentId) {
        return uploadDocument(fileResource, originalFilename, documentId, FastApiDocumentMetadata.EMPTY);
    }

    /**
     * 파일 Resource와 문서 메타데이터를 FastAPI에 전송해 청킹·임베딩·저장을 요청한다.
     *
     * <p>AI 서버가 422로 거절하면(암호·배포용 HWP 등) 응답의 이유 문장을 담은 DOCUMENT_UNREADABLE을 던진다.</p>
     *
     * @param fileResource     FastAPI에 전달할 파일 Resource
     * @param originalFilename multipart filename으로 전달할 원본 파일명
     * @param documentId       MySQL documents PK
     * @param metadata         청크마다 넣을 문서 메타데이터. 값이 없는 칸은 보내지 않는다
     * @return FastAPI 문서 처리 결과
     */
    public FastApiUploadResponse uploadDocument(
            Resource fileResource,
            String originalFilename,
            Long documentId,
            FastApiDocumentMetadata metadata
    ) {
        // MultipartBodyBuilder: multipart/form-data 파트를 생성하고 boundary는 WebClient가 자동 생성
        MultipartBodyBuilder body = new MultipartBodyBuilder();
        // Resource 기반 전송: 파일 전체를 힙에 올리지 않고 multipart writer가 스트리밍 처리한다
        body.part("file", fileResource)
                .filename(Objects.requireNonNullElse(originalFilename, "upload"));
        // FastAPI Form 필드는 문자열로 수신 후 int로 자동 변환함
        body.part("document_id", documentId.toString());
        addMetadataParts(body, metadata);

        try {
            FastApiUploadResponse response = blockingWebClient.post()
                    .uri("/documents")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(BodyInserters.fromMultipartData(body.build()))
                    .retrieve()
                    .bodyToMono(FastApiUploadResponse.class)
                    .block(responseTimeout);
            return Objects.requireNonNull(response, "FastAPI /documents 응답이 null입니다.");
        } catch (WebClientResponseException.ServiceUnavailable e) {
            log.warn("FastAPI /documents 서비스 불가. documentId={}", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_UNAVAILABLE);
        } catch (WebClientResponseException e) {
            // 422는 상태 코드 숫자로 본다(Spring 7에서 예외 이름이 UnprocessableEntity → UnprocessableContent로 바뀜)
            String reason = e.getStatusCode().value() == 422 ? unreadableReason(e) : null;
            if (reason == null) {
                // 422가 아니거나 detail이 문장이 아니면(요청 검증 오류 목록 등) 일반 실패로 둔다
                log.warn("FastAPI /documents 호출 실패. documentId={} status={}", documentId, e.getStatusCode(), e);
                throw new CustomException(ErrorCode.FASTAPI_UPLOAD_FAILED);
            }
            log.warn("FastAPI /documents 문서 거절. documentId={} reason={}", documentId, reason);
            throw new CustomException(ErrorCode.DOCUMENT_UNREADABLE, reason);
        } catch (WebClientRequestException e) {
            log.warn("FastAPI /documents 연결 실패. documentId={}", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_CONNECTION_FAILED);
        } catch (IllegalStateException e) {
            // .block(Duration) 타임아웃 시 Reactor가 IllegalStateException을 던진다
            log.warn("FastAPI /documents 응답 타임아웃. documentId={}", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_TIMEOUT);
        } catch (RuntimeException e) {
            log.warn("FastAPI /documents 호출 실패. documentId={}", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_UPLOAD_FAILED);
        }
    }

    /**
     * 질문을 FastAPI에 전송해 RAG 파이프라인 실행을 요청한다.
     *
     * @param question 사용자 질문
     * @param topK     검색할 유사 청크 수
     * @return FastAPI 질의응답 결과
     */
    public FastApiQueryResponse query(String question, int topK) {
        return query(question, topK, null);
    }

    /**
     * 질문과 관리자 시스템 프롬프트를 FastAPI에 전송해 RAG 파이프라인 실행을 요청한다.
     *
     * @param question     사용자 질문
     * @param topK         검색할 유사 청크 수
     * @param systemPrompt 관리자 프롬프트 설정. null이면 FastAPI 기본 프롬프트를 사용한다.
     * @return FastAPI 질의응답 결과
     */
    public FastApiQueryResponse query(String question, int topK, String systemPrompt) {
        FastApiQueryRequest queryRequest = FastApiQueryRequest.builder()
                .question(question)
                .topK(topK)
                .systemPrompt(systemPrompt)
                .build();

        try {
            FastApiQueryResponse response = blockingWebClient.post()
                    .uri("/query")
                    .contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(queryRequest)
                    .retrieve()
                    .bodyToMono(FastApiQueryResponse.class)
                    .block(responseTimeout);
            // FastAPI 응답이 null인 경우 명시적 예외로 변환
            return Objects.requireNonNull(response, "FastAPI /query 응답이 null입니다.");
        } catch (WebClientResponseException.ServiceUnavailable e) {
            log.warn("FastAPI /query 서비스 불가. topK={}", topK, e);
            throw new CustomException(ErrorCode.FASTAPI_UNAVAILABLE);
        } catch (WebClientRequestException e) {
            log.warn("FastAPI /query 연결 실패. topK={}", topK, e);
            throw new CustomException(ErrorCode.FASTAPI_CONNECTION_FAILED);
        } catch (IllegalStateException e) {
            // .block(Duration) 타임아웃 시 Reactor가 IllegalStateException을 던진다
            log.warn("FastAPI /query 응답 타임아웃. topK={}", topK, e);
            throw new CustomException(ErrorCode.FASTAPI_TIMEOUT);
        } catch (RuntimeException e) {
            log.warn("FastAPI /query 호출 실패. topK={}", topK, e);
            throw new CustomException(ErrorCode.FASTAPI_QUERY_FAILED);
        }
    }

    /**
     * ChromaDB에서 해당 document_id의 청크를 삭제하도록 FastAPI에 요청한다.
     * Spring Boot 논리 삭제와 쌍으로 호출되어 RAG 검색에서 해당 문서가 제외되도록 한다.
     *
     * @param documentId 삭제할 문서의 PK
     */
    public void deleteDocument(Long documentId) {
        try {
            blockingWebClient.delete()
                    .uri("/documents/{id}", documentId)
                    .retrieve()
                    .bodyToMono(Void.class)
                    .block(responseTimeout);
        } catch (WebClientResponseException.ServiceUnavailable e) {
            log.warn("FastAPI DELETE /documents/{} 서비스 불가", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_UNAVAILABLE);
        } catch (WebClientRequestException e) {
            log.warn("FastAPI DELETE /documents/{} 연결 실패", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_CONNECTION_FAILED);
        } catch (IllegalStateException e) {
            // .block(Duration) 타임아웃 시 Reactor가 IllegalStateException을 던진다
            log.warn("FastAPI DELETE /documents/{} 응답 타임아웃", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_TIMEOUT);
        } catch (RuntimeException e) {
            log.warn("FastAPI DELETE /documents/{} 호출 실패", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_DELETE_FAILED);
        }
    }

    /**
     * ChromaDB에 저장된 특정 문서의 청크 목록을 FastAPI에서 조회한다.
     *
     * @param documentId 조회할 문서의 PK
     * @return 청크 목록
     */
    public List<FastApiDocumentChunkResponse> listDocumentChunks(Long documentId) {
        try {
            FastApiDocumentChunksResponse response = blockingWebClient.get()
                    .uri("/documents/{id}/chunks", documentId)
                    .retrieve()
                    .bodyToMono(FastApiDocumentChunksResponse.class)
                    .block(responseTimeout);
            List<FastApiDocumentChunkResponse> chunks =
                    Objects.requireNonNull(response, "FastAPI /documents/{id}/chunks 응답이 null입니다.").getChunks();
            return chunks != null ? chunks : List.of();
        } catch (WebClientResponseException.ServiceUnavailable e) {
            log.warn("FastAPI GET /documents/{}/chunks 서비스 불가", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_UNAVAILABLE);
        } catch (WebClientRequestException e) {
            log.warn("FastAPI GET /documents/{}/chunks 연결 실패", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_CONNECTION_FAILED);
        } catch (IllegalStateException e) {
            // .block(Duration) 타임아웃 시 Reactor가 IllegalStateException을 던진다
            log.warn("FastAPI GET /documents/{}/chunks 응답 타임아웃", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_TIMEOUT);
        } catch (RuntimeException e) {
            log.warn("FastAPI GET /documents/{}/chunks 호출 실패", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_QUERY_FAILED);
        }
    }

    /**
     * FastAPI에서 진행 중인 문서 처리 progress를 조회한다.
     *
     * @param documentId 조회할 문서의 PK
     * @return 문서 처리 진행률
     */
    public FastApiDocumentProgressResponse getDocumentProgress(Long documentId) {
        try {
            FastApiDocumentProgressResponse response = blockingWebClient.get()
                    .uri("/documents/{id}/progress", documentId)
                    .retrieve()
                    .bodyToMono(FastApiDocumentProgressResponse.class)
                    .block(responseTimeout);
            return Objects.requireNonNull(response, "FastAPI /documents/{id}/progress 응답이 null입니다.");
        } catch (WebClientResponseException.ServiceUnavailable e) {
            log.warn("FastAPI GET /documents/{}/progress 서비스 불가", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_UNAVAILABLE);
        } catch (WebClientRequestException e) {
            log.warn("FastAPI GET /documents/{}/progress 연결 실패", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_CONNECTION_FAILED);
        } catch (IllegalStateException e) {
            // .block(Duration) 타임아웃 시 Reactor가 IllegalStateException을 던진다
            log.warn("FastAPI GET /documents/{}/progress 응답 타임아웃", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_TIMEOUT);
        } catch (RuntimeException e) {
            log.warn("FastAPI GET /documents/{}/progress 호출 실패", documentId, e);
            throw new CustomException(ErrorCode.FASTAPI_QUERY_FAILED);
        }
    }

    /**
     * FastAPI /query/stream SSE 엔드포인트를 구독한다.
     * ServerSentEvent 디코더가 SSE 포맷을 자동 파싱하므로 data 접두사 제거는 필요 없다.
     *
     * @param question 사용자 질문
     * @param topK     검색할 유사 청크 수
     * @return SSE data 필드 JSON 문자열 Flux
     */
    public Flux<String> streamQuery(String question, int topK) {
        return streamQuery(question, topK, null);
    }

    /**
     * FastAPI /query/stream SSE 엔드포인트를 관리자 시스템 프롬프트와 함께 구독한다.
     *
     * @param question     사용자 질문
     * @param topK         검색할 유사 청크 수
     * @param systemPrompt 관리자 프롬프트 설정. null이면 FastAPI 기본 프롬프트를 사용한다.
     * @return SSE data 필드 JSON 문자열 Flux
     */
    public Flux<String> streamQuery(String question, int topK, String systemPrompt) {
        return streamingWebClient.post()
                .uri("/query/stream")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(FastApiQueryRequest.builder()
                        .question(question)
                        .topK(topK)
                        .systemPrompt(systemPrompt)
                        .build())
                .retrieve()
                .bodyToFlux(new ParameterizedTypeReference<ServerSentEvent<String>>() {})
                .map(ServerSentEvent::data)
                .filter(data -> data != null && !data.isEmpty());
    }

    // 값이 있는 메타데이터만 multipart 파트로 붙인다. 이름은 FastAPI Form 인자와 같다
    private static void addMetadataParts(MultipartBodyBuilder body, FastApiDocumentMetadata metadata) {
        if (metadata == null) {
            return;
        }
        addPart(body, "ledger_id", metadata.ledgerId());
        addPart(body, "source_url", metadata.sourceUrl());
        addPart(body, "posted_at", metadata.postedAt());
        addPart(body, "academic_year", metadata.academicYear());
        addPart(body, "category_id", metadata.categoryId());
        addPart(body, "category", metadata.categoryName());
    }

    private static void addPart(MultipartBodyBuilder body, String name, Object value) {
        if (value != null) {
            body.part(name, value.toString());
        }
    }

    // AI 서버 422 응답의 detail이 문장이면 돌려준다(화면에 보여도 되는 이유). 아니면 null
    private static String unreadableReason(WebClientResponseException e) {
        try {
            JsonNode detail = new ObjectMapper().readTree(e.getResponseBodyAsString()).path("detail");
            return detail.isTextual() && !detail.asText().isBlank() ? detail.asText() : null;
        } catch (JsonProcessingException parseError) {
            return null;
        }
    }
}
