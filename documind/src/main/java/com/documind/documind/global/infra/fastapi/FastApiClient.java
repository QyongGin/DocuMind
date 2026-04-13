package com.documind.documind.global.infra.fastapi;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;

// FastAPI 서버와 통신하는 HTTP 클라이언트
// @Component: 스프링 빈으로 등록
@Component
public class FastApiClient {

    private final RestTemplate restTemplate;
    private final String baseUrl;

    // application.yaml의 fastapi.url 값을 주입. Docker에서는 환경변수 FASTAPI_URL로 오버라이드
    public FastApiClient(@Value("${fastapi.url}") String baseUrl) {
        this.restTemplate = new RestTemplate();
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
}
