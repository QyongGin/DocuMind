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
     *
     * <p>출처 정보(대장 ID·원래 주소·게시일·학년도)와 게시 정보(사이트·게시판·제목·첨부의 게시글, ADR-0051)는
     * 모두 선택이다. 대량 업로드 명령은 대장 값을, 관리자 화면은 '추가 정보(선택)' 입력을 보낸다.
     * 같은 파일이 이미 있으면 409와 기존 문서를 돌려준다.</p>
     */
    @PostMapping
    public ResponseEntity<ApiResponse<DocumentUploadResponse>> upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "categoryId", required = false) Long categoryId,
            @RequestParam(value = "ledgerId", required = false) String ledgerId,
            @RequestParam(value = "sourceUrl", required = false) String sourceUrl,
            @RequestParam(value = "sourcePostedAt", required = false) String sourcePostedAt,
            @RequestParam(value = "academicYear", required = false) Integer academicYear,
            @RequestParam(value = "originSite", required = false) String originSite,
            @RequestParam(value = "originSiteName", required = false) String originSiteName,
            @RequestParam(value = "originBoard", required = false) String originBoard,
            @RequestParam(value = "originTitle", required = false) String originTitle,
            @RequestParam(value = "originParentTitle", required = false) String originParentTitle,
            @RequestParam(value = "originParentUrl", required = false) String originParentUrl,
            @AuthenticationPrincipal String username
    ) {
        DocumentSource source = DocumentSource.of(ledgerId, sourceUrl, sourcePostedAt, academicYear);
        DocumentOrigin origin = new DocumentOrigin(originSite, originSiteName, originBoard, originTitle,
                originParentTitle, originParentUrl);
        DocumentUploadResponse response = documentService.upload(file, categoryId, source, origin, username);
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
     * GET /api/documents/{id}/chunks — 문서별 ChromaDB 청크 원문 조회 (ADMIN 전용).
     *
     * @param id 청크를 조회할 문서 PK
     * @return 문서의 청크 목록
     */
    @GetMapping("/{id}/chunks")
    public ResponseEntity<ApiResponse<List<DocumentChunkResponse>>> chunks(@PathVariable Long id) {
        return ResponseEntity.ok(ApiResponse.success(documentService.listChunks(id)));
    }

    /**
     * GET /api/documents/{id}/progress — 문서 색인 진행률 조회 (ADMIN 전용).
     *
     * @param id progress를 조회할 문서 PK
     * @return 문서 처리 진행률
     */
    @GetMapping("/{id}/progress")
    public ResponseEntity<ApiResponse<DocumentProgressResponse>> progress(@PathVariable Long id) {
        return ResponseEntity.ok(ApiResponse.success(documentService.progress(id)));
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
