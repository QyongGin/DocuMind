package com.documind.documind.global.infra.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * FastAPI POST /documents 응답을 역직렬화하는 DTO.
 * FastAPI 응답 형식: {"status": "success", "filename": "...", "chunks": 42}
 */
@Getter
// @NoArgsConstructor: Jackson 역직렬화에 기본 생성자가 필요하다
@NoArgsConstructor
// @AllArgsConstructor: 테스트에서 Mock 응답 생성에 사용한다
@AllArgsConstructor
public class FastApiUploadResponse {

    private String status;
    private String filename;

    // FastAPI가 "chunks"로 내려주므로 JSON 필드명을 명시
    @JsonProperty("chunks")
    private int chunks;
}
