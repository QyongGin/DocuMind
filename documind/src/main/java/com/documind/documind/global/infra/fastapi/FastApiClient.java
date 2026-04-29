package com.documind.documind.global.infra.fastapi;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.Objects;

// FastAPI 서버와 통신하는 HTTP 클라이언트
// @Component: 스프링 빈으로 등록
@Component
public class FastApiClient {

    private final RestTemplate restTemplate;
    private final String baseUrl;

    // application.yaml의 fastapi.url 값을 주입. Docker에서는 환경변수 FASTAPI_URL로 오버라이드
    public FastApiClient(@Value("${fastapi.url}") String baseUrl) {
        // LLM 추론이 길어질 수 있으므로 readTimeout을 120초로 설정. connectTimeout은 서버 다운 감지용 5초
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5_000);
        factory.setReadTimeout(120_000);
        this.restTemplate = new RestTemplate(factory);
        this.baseUrl = baseUrl;
    }

    // PDF 파일과 document_id를 FastAPI에 전송해 청킹·임베딩·저장을 요청
    public FastApiUploadResponse uploadDocument(MultipartFile file, Long documentId) {
        // RestTemplate + HttpEntity<MultiValueMap> 방식: multipart/form-data 전송의 검증된 방법
        // FormHttpMessageConverter가 boundary를 자동 생성하고 Content-Type 헤더에 주입함
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();

        try {
            byte[] bytes = file.getBytes();
            // getFilename() 오버라이드: Content-Disposition의 filename 파라미터로 원본 파일명 전달
            ByteArrayResource fileResource = new ByteArrayResource(bytes) {
                @Override
                public String getFilename() {
                    return file.getOriginalFilename();
                }
            };
            body.add("file", fileResource);
        } catch (IOException e) {
            throw new CustomException(ErrorCode.FILE_READ_FAILED);
        }

        // document_id는 String으로 추가: FormHttpMessageConverter가 문자열 파트로 직렬화
        // FastAPI Form 필드는 문자열로 수신 후 int로 자동 변환함
        body.add("document_id", documentId.toString());

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.MULTIPART_FORM_DATA);

        HttpEntity<MultiValueMap<String, Object>> requestEntity = new HttpEntity<>(body, headers);

        return restTemplate.postForObject(
                baseUrl + "/documents",
                requestEntity,
                FastApiUploadResponse.class
        );
    }

    // 질문을 FastAPI에 전송해 RAG 파이프라인(임베딩 → 검색 → LLM 추론) 실행을 요청
    public FastApiQueryResponse query(String question, int topK) {
        // 업로드와 달리 파일 전송이 없으므로 JSON body로 전송
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        FastApiQueryRequest queryRequest = FastApiQueryRequest.builder()
                .question(question)
                .topK(topK)
                .build();

        HttpEntity<FastApiQueryRequest> requestEntity = new HttpEntity<>(queryRequest, headers);

        try {
            FastApiQueryResponse response = restTemplate.postForObject(
                    baseUrl + "/query",
                    requestEntity,
                    FastApiQueryResponse.class
            );
            // FastAPI 응답이 null인 경우 명시적 예외로 변환
            return Objects.requireNonNull(response, "FastAPI /query 응답이 null입니다.");
        } catch (RestClientException e) {
            throw new CustomException(ErrorCode.FASTAPI_QUERY_FAILED);
        }
    }
}
