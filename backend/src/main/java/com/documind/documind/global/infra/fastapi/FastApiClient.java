package com.documind.documind.global.infra.fastapi;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Component;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;

import java.time.Duration;
import java.util.Objects;

// FastAPI 서버와 통신하는 HTTP 클라이언트
// @Component: 스프링 빈으로 등록
@Component
public class FastApiClient {

    private final WebClient webClient;
    private final Duration responseTimeout;

    public FastApiClient(
            WebClient fastApiWebClient,
            @Value("${fastapi.response-timeout:180s}") Duration responseTimeout
    ) {
        this.webClient = fastApiWebClient;
        this.responseTimeout = responseTimeout;
    }

    // PDF 파일과 document_id를 FastAPI에 전송해 청킹·임베딩·저장을 요청
    public FastApiUploadResponse uploadDocument(MultipartFile file, Long documentId) {
        // MultipartBodyBuilder: multipart/form-data 파트를 생성하고 boundary는 WebClient가 자동 생성
        MultipartBodyBuilder body = new MultipartBodyBuilder();
        // MultipartFile#getResource(): 파일 전체를 힙에 올리지 않고 Resource로 전달
        body.part("file", file.getResource())
                .filename(Objects.requireNonNullElse(file.getOriginalFilename(), "upload"));
        // FastAPI Form 필드는 문자열로 수신 후 int로 자동 변환함
        body.part("document_id", documentId.toString());

        try {
            FastApiUploadResponse response = webClient.post()
                    .uri("/documents")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(BodyInserters.fromMultipartData(body.build()))
                    .retrieve()
                    .bodyToMono(FastApiUploadResponse.class)
                    .block(responseTimeout);
            return Objects.requireNonNull(response, "FastAPI /documents 응답이 null입니다.");
        } catch (RuntimeException e) {
            throw new CustomException(ErrorCode.FASTAPI_UPLOAD_FAILED);
        }
    }

    // 질문을 FastAPI에 전송해 RAG 파이프라인(임베딩 → 검색 → LLM 추론) 실행을 요청
    public FastApiQueryResponse query(String question, int topK) {
        FastApiQueryRequest queryRequest = FastApiQueryRequest.builder()
                .question(question)
                .topK(topK)
                .build();

        try {
            FastApiQueryResponse response = webClient.post()
                    .uri("/query")
                    .contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(queryRequest)
                    .retrieve()
                    .bodyToMono(FastApiQueryResponse.class)
                    .block(responseTimeout);
            // FastAPI 응답이 null인 경우 명시적 예외로 변환
            return Objects.requireNonNull(response, "FastAPI /query 응답이 null입니다.");
        } catch (RuntimeException e) {
            throw new CustomException(ErrorCode.FASTAPI_QUERY_FAILED);
        }
    }

    // FastAPI /query/stream SSE 엔드포인트를 구독해 data 필드 JSON 문자열 Flux를 반환
    // ServerSentEvent<String> 디코더가 SSE 포맷을 자동 파싱하므로 "data: " 접두사 제거 불필요
    public Flux<String> streamQuery(String question, int topK) {
        return webClient.post()
                .uri("/query/stream")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(FastApiQueryRequest.builder()
                        .question(question)
                        .topK(topK)
                        .build())
                .retrieve()
                .bodyToFlux(new ParameterizedTypeReference<ServerSentEvent<String>>() {})
                .map(ServerSentEvent::data)
                .filter(data -> data != null && !data.isEmpty());
    }
}
