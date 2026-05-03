package com.documind.documind.domain.document;

import com.documind.documind.global.common.ApiResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 문서 관련 엔드포인트를 처리하는 컨트롤러.
 * 업로드·목록 조회·삭제는 ADMIN 전용 (SecurityConfig에서 제어).
 */
// @RestController: @Controller + @ResponseBody. JSON 응답을 자동으로 직렬화
@RestController
@RequestMapping("/api/documents")
@RequiredArgsConstructor
public class DocumentController {

    private final DocumentService documentService;

    /**
     * POST /api/documents — 문서 업로드 (ADMIN 전용).
     * @RequestParam: multipart/form-data에서 각 파트를 개별 파라미터로 바인딩한다.
     */
    @PostMapping
    public ResponseEntity<ApiResponse<DocumentUploadResponse>> upload(
            @RequestParam("file") MultipartFile file,
            @AuthenticationPrincipal String username
    ) {
        DocumentUploadResponse response = documentService.upload(file, username);
        return ResponseEntity.ok(ApiResponse.success(response));
    }

    /**
     * GET /api/documents — 활성화된 문서 목록 조회 (ADMIN 전용).
     *
     * @return 최신순 문서 목록
     */
    @GetMapping
    public ResponseEntity<ApiResponse<List<DocumentListResponse>>> list() {
        return ResponseEntity.ok(ApiResponse.success(documentService.list()));
    }

    /**
     * DELETE /api/documents/{id} — 문서 논리 삭제 + ChromaDB 청크 제거 (ADMIN 전용).
     *
     * @param id 삭제할 문서 PK
     * @return 204 No Content
     */
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable Long id) {
        documentService.delete(id);
        return ResponseEntity.noContent().build();
    }
}
