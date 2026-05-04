package com.documind.documind.domain.document;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.User.Role;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.domain.category.Category;
import com.documind.documind.domain.category.CategoryCreateRequest;
import com.documind.documind.domain.category.CategoryRepository;
import com.documind.documind.domain.category.CategoryResponse;
import com.documind.documind.domain.category.CategoryService;
import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiUploadResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.*;

/**
 * 문서 관리 서비스 통합 테스트.
 * FastApiClient는 @MockitoBean으로 대체해 외부 HTTP 호출을 격리한다.
 */
// @SpringBootTest: 전체 애플리케이션 컨텍스트를 로드해 실제 DB(H2 인메모리) 기반으로 검증한다.
// @ActiveProfiles: 테스트 전용 application-test.yaml 설정을 로드한다.
@SpringBootTest
@ActiveProfiles("test")
class DocumentManagementTest {

    @Autowired
    private DocumentService documentService;

    @Autowired
    private DocumentRepository documentRepository;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private CategoryService categoryService;

    @Autowired
    private CategoryRepository categoryRepository;

    // FastApiClient의 실제 HTTP 호출을 Mock으로 대체
    @MockitoBean
    private FastApiClient fastApiClient;

    private User admin;
    private Document activeDoc;
    private static final String ADMIN_USERNAME = "admin";

    @BeforeEach
    void setUp() {
        // 관리자 계정 생성
        admin = userRepository.save(User.create(ADMIN_USERNAME, "encoded-password", Role.ADMIN));

        // 활성 문서 직접 저장 (업로드 파이프라인 우회)
        activeDoc = documentRepository.save(
                Document.create(admin, null, "uuid-file.pdf", "sample.pdf", 1024L, "application/pdf")
        );
    }

    @AfterEach
    void tearDown() {
        documentRepository.deleteAll();
        categoryRepository.deleteAll();
        userRepository.deleteAll();
    }

    @Test
    @DisplayName("문서 목록 조회 - 활성 문서만 반환한다")
    void list_returnsOnlyActiveDocuments() {
        // 논리 삭제된 문서 추가
        Document inactiveDoc = documentRepository.save(
                Document.create(admin, null, "inactive.pdf", "inactive.pdf", 512L, "application/pdf")
        );
        inactiveDoc.deactivate();
        documentRepository.save(inactiveDoc);

        List<DocumentListResponse> result = documentService.list();

        assertEquals(1, result.size());
        assertEquals("sample.pdf", result.get(0).getOriginalName());
    }

    @Test
    @DisplayName("문서 목록 조회 - 최신순으로 정렬한다")
    void list_orderedByCreatedAtDesc() throws InterruptedException {
        // createdAt이 @PrePersist에서 LocalDateTime.now()로 설정되므로
        // 저장 사이에 최소 1ms 간격을 두어 정렬 순서를 결정론적으로 만든다
        Thread.sleep(2);
        documentRepository.save(
                Document.create(admin, null, "older.pdf", "older.pdf", 512L, "application/pdf")
        );
        Thread.sleep(2);
        documentRepository.save(
                Document.create(admin, null, "newest.pdf", "newest.pdf", 512L, "application/pdf")
        );

        List<DocumentListResponse> result = documentService.list();

        // 가장 최근에 저장된 문서가 목록의 첫 번째여야 한다
        assertEquals("newest.pdf", result.get(0).getOriginalName());
    }

    @Test
    @DisplayName("문서 삭제 - is_active=false로 변경하고 FastAPI 청크 삭제를 호출한다")
    void delete_deactivatesDocumentAndCallsFastApi() {
        doNothing().when(fastApiClient).deleteDocument(anyLong());

        documentService.delete(activeDoc.getId());

        Document deleted = documentRepository.findById(activeDoc.getId()).orElseThrow();
        assertFalse(deleted.getIsActive());
        verify(fastApiClient, times(1)).deleteDocument(activeDoc.getId());
    }

    @Test
    @DisplayName("문서 삭제 - FastAPI 호출 실패 시 트랜잭션이 롤백되어 문서가 활성 상태를 유지한다")
    void delete_fastApiFailureRollsBackDeactivation() {
        // FastApiClient의 계약: 삭제 실패 시 CustomException(FASTAPI_DELETE_FAILED)를 던진다
        doThrow(new CustomException(ErrorCode.FASTAPI_DELETE_FAILED))
                .when(fastApiClient).deleteDocument(anyLong());

        CustomException ex = assertThrows(CustomException.class,
                () -> documentService.delete(activeDoc.getId()));
        assertEquals(ErrorCode.FASTAPI_DELETE_FAILED, ex.getErrorCode());

        Document doc = documentRepository.findById(activeDoc.getId()).orElseThrow();
        assertTrue(doc.getIsActive(),
                "FastAPI 실패 시 @Transactional 롤백으로 isActive가 true를 유지해야 한다");
    }

    @Test
    @DisplayName("문서 삭제 - 존재하지 않는 ID는 DOCUMENT_NOT_FOUND 예외를 반환한다")
    void delete_notFoundThrowsException() {
        CustomException ex = assertThrows(CustomException.class,
                () -> documentService.delete(99999L));
        assertEquals(ErrorCode.DOCUMENT_NOT_FOUND, ex.getErrorCode());
    }

    @Test
    @DisplayName("문서 삭제 - 이미 논리 삭제된 문서는 DOCUMENT_NOT_FOUND 예외를 반환한다")
    void delete_alreadyDeactivatedThrowsException() {
        activeDoc.deactivate();
        documentRepository.save(activeDoc);

        CustomException ex = assertThrows(CustomException.class,
                () -> documentService.delete(activeDoc.getId()));
        assertEquals(ErrorCode.DOCUMENT_NOT_FOUND, ex.getErrorCode());
    }

    @Test
    @DisplayName("문서 업로드 - FastAPI 응답 청크 수가 Document에 반영된다")
    void upload_chunkCountUpdated() {
        when(fastApiClient.uploadDocument(any(), anyLong()))
                .thenReturn(new FastApiUploadResponse("success", "report.pdf", 7));

        MockMultipartFile file = new MockMultipartFile(
                "file", "report.pdf", "application/pdf", new byte[100]
        );

        DocumentUploadResponse response = documentService.upload(file, ADMIN_USERNAME);

        assertEquals(7, response.getChunkCount());
        assertEquals("report.pdf", response.getOriginalName());
    }

    @Test
    @DisplayName("문서 업로드 - 허용하지 않는 파일 형식은 INVALID_FILE_TYPE 예외를 반환한다")
    void upload_invalidMimeTypeThrowsException() {
        MockMultipartFile file = new MockMultipartFile(
                "file", "image.png", "image/png", new byte[10]
        );

        CustomException ex = assertThrows(CustomException.class,
                () -> documentService.upload(file, ADMIN_USERNAME));
        assertEquals(ErrorCode.INVALID_FILE_TYPE, ex.getErrorCode());
    }

    @Test
    @DisplayName("카테고리 생성 - 이름이 저장되고 응답에 반환된다")
    void categoryCreate_success() {
        // @AllArgsConstructor를 사용해 리플렉션 없이 직접 생성
        CategoryCreateRequest req = new CategoryCreateRequest("기술문서");

        CategoryResponse result = categoryService.create(req);

        assertEquals("기술문서", result.getName());
        assertNotNull(result.getId());
        assertNotNull(result.getCreatedAt());
    }

    @Test
    @DisplayName("카테고리 생성 - 중복 이름은 CATEGORY_ALREADY_EXISTS 예외를 반환한다")
    void categoryCreate_duplicateNameThrowsException() {
        categoryRepository.save(Category.create("정책문서"));

        CategoryCreateRequest req = new CategoryCreateRequest("정책문서");

        CustomException ex = assertThrows(CustomException.class,
                () -> categoryService.create(req));
        assertEquals(ErrorCode.CATEGORY_ALREADY_EXISTS, ex.getErrorCode());
    }

    @Test
    @DisplayName("카테고리 목록 조회 - 이름 오름차순으로 반환한다")
    void categoryList_orderedByNameAsc() {
        categoryRepository.save(Category.create("인사문서"));
        categoryRepository.save(Category.create("기술문서"));
        categoryRepository.save(Category.create("재무문서"));

        List<CategoryResponse> result = categoryService.list();

        assertEquals("기술문서", result.get(0).getName());
        assertEquals("인사문서", result.get(1).getName());
        assertEquals("재무문서", result.get(2).getName());
    }

    @Test
    @DisplayName("카테고리 목록 조회 - 카테고리가 없으면 빈 목록을 반환한다")
    void categoryList_emptyReturnsEmptyList() {
        List<CategoryResponse> result = categoryService.list();
        assertTrue(result.isEmpty());
    }
}
