package com.documind.documind.global.infra.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;

// FastAPI POST /documents 응답을 역직렬화하는 DTO
// FastAPI 응답 형식: {"status": "success", "filename": "...", "chunks": 42}
@Getter
public class FastApiUploadResponse {

    private String status;
    private String filename;

    // FastAPI가 "chunks"로 내려주므로 JSON 필드명을 명시
    @JsonProperty("chunks")
    private int chunks;
}
