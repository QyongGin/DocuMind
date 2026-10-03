package com.documind.documind.domain.document;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.global.auth.JwtProvider;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiDocumentMetadata;
import com.documind.documind.global.infra.fastapi.FastApiUploadResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.multipart.MultipartFile;

import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.Arrays;

import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.startsWith;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 문서 업로드 API(#126): 출처 칸 바인딩, 출처 형식 오류 400, 같은 파일 409의 응답 모양.
 * 대량 업로드 명령(`tools/corpus upload`)이 409 응답의 data.documentId를 기록하므로 모양을 고정한다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class DocumentUploadApiTest {

    private static final byte[] PDF_BYTES = Arrays.copyOf("%PDF-1.4\n".getBytes(StandardCharsets.US_ASCII), 64);

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private DocumentRepository documentRepository;

    @Autowired
    private DocumentService documentService;

    @Autowired
    private JwtProvider jwtProvider;

    @MockitoBean
    private FastApiClient fastApiClient;

    private User admin;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(documentService, "asyncProcessingEnabled", false);
        admin = userRepository.save(User.create("admin", "encoded-password", User.Role.ADMIN));
        when(fastApiClient.uploadDocument(any(MultipartFile.class), anyLong(), any(FastApiDocumentMetadata.class)))
                .thenReturn(new FastApiUploadResponse("success", "report.pdf", 3));
    }

    @AfterEach
    void tearDown() {
        documentRepository.deleteAll();
        userRepository.deleteAll();
    }

    @Test
    @DisplayName("업로드 API - 출처 칸을 받아 저장한다")
    void upload_bindsSourceFields() throws Exception {
        mockMvc.perform(multipart("/api/documents")
                        .file(new MockMultipartFile("file", "report.pdf", "application/pdf", PDF_BYTES))
                        .param("ledgerId", "www/bbs/11/1/a2")
                        .param("sourceUrl", "https://www.example.ac.kr/notice/1")
                        .param("sourcePostedAt", "2026-08-01")
                        .param("academicYear", "2026")
                        .header("Authorization", bearer()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success", is(true)));

        Document saved = documentRepository.findAll().get(0);
        assertEquals(new DocumentSource("www/bbs/11/1/a2", "https://www.example.ac.kr/notice/1",
                LocalDate.of(2026, 8, 1), 2026), saved.getSource());
    }

    @Test
    @DisplayName("업로드 API - 출처 형식이 틀리면 400과 어느 칸인지 알려 준다")
    void upload_rejectsInvalidSource() throws Exception {
        mockMvc.perform(multipart("/api/documents")
                        .file(new MockMultipartFile("file", "report.pdf", "application/pdf", PDF_BYTES))
                        .param("sourcePostedAt", "2026/08/01")
                        .header("Authorization", bearer()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message", startsWith("게시일")));
    }

    @Test
    @DisplayName("업로드 API - 같은 파일은 409와 기존 문서 번호·이름을 data로 돌려준다")
    void upload_duplicateReturnsExistingDocument() throws Exception {
        mockMvc.perform(multipart("/api/documents")
                        .file(new MockMultipartFile("file", "report.pdf", "application/pdf", PDF_BYTES))
                        .header("Authorization", bearer()))
                .andExpect(status().isOk());
        Long existingId = documentRepository.findAll().get(0).getId();

        mockMvc.perform(multipart("/api/documents")
                        .file(new MockMultipartFile("file", "copy.pdf", "application/pdf", PDF_BYTES))
                        .header("Authorization", bearer()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.success", is(false)))
                .andExpect(jsonPath("$.message", is("이미 올린 문서입니다: report.pdf")))
                .andExpect(jsonPath("$.data.documentId", is(existingId.intValue())))
                .andExpect(jsonPath("$.data.originalName", is("report.pdf")));
    }

    private String bearer() {
        return "Bearer " + jwtProvider.generateToken(admin.getUsername(), admin.getRole().name(), admin.getId());
    }
}
