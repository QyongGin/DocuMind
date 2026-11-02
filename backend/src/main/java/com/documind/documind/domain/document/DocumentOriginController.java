package com.documind.documind.domain.document;

import com.documind.documind.global.common.ApiResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 이미 올린 문서의 게시 정보(사이트·게시판·제목·첨부의 게시글)를 채우는 관리자 API(ADR-0051 결정 2).
 * 경로가 /api/admin 아래라 ADMIN만 부른다(SecurityConfig).
 */
@RestController
@RequestMapping("/api/admin/documents/origins")
@RequiredArgsConstructor
public class DocumentOriginController {

    private final DocumentService documentService;

    /**
     * PUT /api/admin/documents/origins — 대장 ID별 게시 정보로 살아 있는 문서를 채운다.
     *
     * @param updates 대장 ID별 게시 정보(한 번에 1,000개까지)
     * @return 바꾼 문서 수와 살아 있는 문서가 없는 대장 ID
     */
    @PutMapping
    public ResponseEntity<ApiResponse<DocumentOriginUpdateResponse>> update(
            @RequestBody List<DocumentOriginUpdateRequest> updates) {
        return ResponseEntity.ok(ApiResponse.success(documentService.updateOrigins(updates)));
    }
}
