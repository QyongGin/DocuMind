package com.documind.documind.global.infra.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.Map;

/**
 * FastAPI /documents/{id}/chunks 응답의 청크 항목 DTO.
 */
@Getter
@NoArgsConstructor
public class FastApiDocumentChunkResponse {

    private String id;

    @JsonProperty("chunk_index")
    private int chunkIndex;

    private String content;

    private Map<String, Object> metadata;
}
