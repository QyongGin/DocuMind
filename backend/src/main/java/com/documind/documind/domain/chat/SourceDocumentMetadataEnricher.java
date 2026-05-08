package com.documind.documind.domain.chat;

import com.documind.documind.domain.document.Document;
import com.documind.documind.domain.document.DocumentRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * FastAPI가 반환한 출처 청크 목록에 Spring Boot가 가진 문서 메타데이터를 보강한다.
 */
@Service
@RequiredArgsConstructor
public class SourceDocumentMetadataEnricher {

    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ISO_LOCAL_DATE_TIME;

    private final DocumentRepository documentRepository;

    /**
     * 출처 목록의 document_id를 기준으로 원본 문서명과 업로드 시각을 추가한다.
     *
     * @param sources FastAPI가 반환한 출처 청크 목록
     * @return 문서 메타데이터가 보강된 출처 청크 목록
     */
    public List<Map<String, Object>> enrich(List<Map<String, Object>> sources) {
        if (sources == null || sources.isEmpty()) {
            return List.of();
        }

        Map<Long, Optional<Document>> documentCache = new HashMap<>();
        return sources.stream()
                .map(source -> enrichSource(source, documentCache))
                .toList();
    }

    private Map<String, Object> enrichSource(Map<String, Object> source, Map<Long, Optional<Document>> documentCache) {
        Map<String, Object> enriched = new LinkedHashMap<>(source);
        parseDocumentId(source.get("document_id"))
                .flatMap(documentId -> documentCache.computeIfAbsent(documentId, documentRepository::findByIdAndIsActiveTrue))
                .ifPresent(document -> addDocumentMetadata(enriched, document));
        return enriched;
    }

    private Optional<Long> parseDocumentId(Object value) {
        if (value == null) {
            return Optional.empty();
        }

        try {
            return Optional.of(Long.parseLong(String.valueOf(value)));
        } catch (NumberFormatException e) {
            return Optional.empty();
        }
    }

    private void addDocumentMetadata(Map<String, Object> source, Document document) {
        source.put("document_original_name", document.getOriginalName());
        source.put("document_uploaded_at", document.getCreatedAt().format(DATE_TIME_FORMATTER));
        source.put("document_chunk_count", document.getChunkCount());
        source.put("document_file_size", document.getFileSize());
    }
}
