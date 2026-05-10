package com.documind.documind.global.infra.fastapi;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
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
        return uploadDocument(
                file.getResource(),
                Objects.requireNonNullElse(file.getOriginalFilename(), "upload"),
                documentId
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
        // MultipartBodyBuilder: multipart/form-data 파트를 생성하고 boundary는 WebClient가 자동 생성
        MultipartBodyBuilder body = new MultipartBodyBuilder();
        // Resource 기반 전송: 파일 전체를 힙에 올리지 않고 multipart writer가 스트리밍 처리한다
        body.part("file", fileResource)
                .filename(Objects.requireNonNullElse(originalFilename, "upload"));
        // FastAPI Form 필드는 문자열로 수신 후 int로 자동 변환함
        body.part("document_id", documentId.toString());

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
}
