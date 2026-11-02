package com.documind.documind.domain.document;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.global.auth.JwtProvider;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.startsWith;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 이미 올린 문서의 게시 정보 채우기 API(ADR-0051, #205): 대장 ID로 찾아 바꾸고, 없는 대장 ID를 알려 주며, ADMIN만 부른다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class DocumentOriginApiTest {

    private static final String ATTACHMENT_LEDGER_ID = "www/bbs/11/1/a2";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private DocumentRepository documentRepository;

    @Autowired
    private JwtProvider jwtProvider;

    private User admin;

    @BeforeEach
    void setUp() {
        admin = userRepository.save(User.create("admin", "encoded-password", User.Role.ADMIN));
        documentRepository.save(Document.create(admin, null, "a.pdf", "수강신청서.pdf", 10L, "application/pdf",
                new DocumentSource(ATTACHMENT_LEDGER_ID, null, null, null), null));
    }

    @AfterEach
    void tearDown() {
        documentRepository.deleteAll();
        userRepository.deleteAll();
    }

    @Test
    @DisplayName("게시 정보 API - 대장 ID로 문서를 찾아 채우고, 살아 있는 문서가 없는 대장 ID를 돌려준다")
    void update_fillsOriginByLedgerId() throws Exception {
        String body = """
                [{"ledgerId": "%s", "site": "www", "siteName": "학교", "board": "학사(11)", "title": "수강신청서.pdf",
                  "parentTitle": "2학기 수강신청 안내", "parentUrl": "https://www.ganada.ac.kr/bbs/11/1"},
                 {"ledgerId": "www/bbs/11/9", "site": "www", "title": "지운 공지"}]
                """.formatted(ATTACHMENT_LEDGER_ID);

        mockMvc.perform(put("/api/admin/documents/origins")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body)
                        .header("Authorization", bearer(admin.getUsername(), User.Role.ADMIN, admin.getId())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.updated", is(1)))
                .andExpect(jsonPath("$.data.missingLedgerIds", contains("www/bbs/11/9")));

        Document saved = documentRepository.findAll().get(0);
        assertEquals(new DocumentOrigin("www", "학교", "학사(11)", "수강신청서.pdf", "2학기 수강신청 안내",
                "https://www.ganada.ac.kr/bbs/11/1"), saved.getOrigin());
    }

    @Test
    @DisplayName("게시 정보 API - 형식이 틀린 칸이 있으면 400과 어느 칸인지 알려 주고 아무것도 바꾸지 않는다")
    void update_rejectsInvalidOrigin() throws Exception {
        String body = """
                [{"ledgerId": "%s", "site": "www", "title": "수강신청서.pdf"},
                 {"ledgerId": "www/bbs/11/2", "parentUrl": "ftp://ganada.ac.kr/a"}]
                """.formatted(ATTACHMENT_LEDGER_ID);

        mockMvc.perform(put("/api/admin/documents/origins")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body)
                        .header("Authorization", bearer(admin.getUsername(), User.Role.ADMIN, admin.getId())))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message", startsWith("게시글 주소")));

        assertEquals(DocumentOrigin.EMPTY, documentRepository.findAll().get(0).getOrigin());
    }

    @Test
    @DisplayName("게시 정보 API - USER 권한 요청은 403을 반환한다")
    void update_userRole_returns403() throws Exception {
        mockMvc.perform(put("/api/admin/documents/origins")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("[{\"ledgerId\": \"" + ATTACHMENT_LEDGER_ID + "\", \"site\": \"www\"}]")
                        .header("Authorization", bearer("user", User.Role.USER, 999L)))
                .andExpect(status().isForbidden());

        assertEquals(DocumentOrigin.EMPTY, documentRepository.findAll().get(0).getOrigin());
    }

    private String bearer(String username, User.Role role, Long id) {
        return "Bearer " + jwtProvider.generateToken(username, role.name(), id);
    }
}
