package com.documind.documind.global.infra.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * FastAPI /documents/{id}/chunks 응답 DTO.
 */
@Getter
@NoArgsConstructor
public class FastApiDocumentChunksResponse {

    @JsonProperty("document_id")
    private Long documentId;

    private List<FastApiDocumentChunkResponse> chunks;
}
