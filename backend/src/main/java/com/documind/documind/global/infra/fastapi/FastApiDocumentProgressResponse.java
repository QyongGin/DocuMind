package com.documind.documind.global.infra.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * FastAPI GET /documents/{id}/progress 응답을 역직렬화하는 DTO.
 */
// @Getter: FastApiClient가 진행률 필드를 읽을 수 있게 getter를 생성한다
@Getter
// @NoArgsConstructor: Jackson 역직렬화에 기본 생성자가 필요하다
@NoArgsConstructor
// @AllArgsConstructor: 테스트에서 Mock 응답 생성에 사용한다
@AllArgsConstructor
public class FastApiDocumentProgressResponse {

    @JsonProperty("document_id")
    private Long documentId;

    private int percent;
    private String stage;
    private String message;
    private String status;
}
