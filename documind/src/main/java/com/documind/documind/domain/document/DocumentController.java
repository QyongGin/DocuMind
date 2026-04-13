package com.documind.documind.domain.document;

import com.documind.documind.global.common.ApiResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

// 문서 관련 엔드포인트를 처리하는 컨트롤러
@RestController
@RequestMapping("/api/documents")
@RequiredArgsConstructor
public class DocumentController {

    private final DocumentService documentService;

    // POST /api/documents - 문서 업로드 (ADMIN 전용)
    // @RequestParam: multipart/form-data에서 각 파트를 개별 파라미터로 바인딩
    @PostMapping
    public ResponseEntity<ApiResponse<DocumentUploadResponse>> upload(
            @RequestParam("file") MultipartFile file,
            @AuthenticationPrincipal String username
    ) {
        DocumentUploadResponse response = documentService.upload(file, username);
        return ResponseEntity.ok(ApiResponse.success(response));
    }
}
