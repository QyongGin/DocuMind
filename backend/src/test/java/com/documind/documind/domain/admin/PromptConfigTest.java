package com.documind.documind.domain.admin;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.global.auth.JwtProvider;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.nullValue;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 관리자 프롬프트 설정 API 통합 테스트이다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class PromptConfigTest {

    private static final String ADMIN_USERNAME = "admin";
    private static final String RAW_PASSWORD = "admin1234";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private PromptConfigRepository promptConfigRepository;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    private JwtProvider jwtProvider;

    // FastApiClient Bean이 컨텍스트에 등록되어 있어 Mock으로 대체해야 컨텍스트 로딩이 성공한다
    @MockitoBean
    private FastApiClient fastApiClient;

    private User admin;

    @BeforeEach
    void setUp() {
        admin = userRepository.save(
                User.create(ADMIN_USERNAME, passwordEncoder.encode(RAW_PASSWORD), User.Role.ADMIN)
        );
    }

    @AfterEach
    void tearDown() {
        promptConfigRepository.deleteAll();
        userRepository.deleteAll();
    }

    @Test
    @DisplayName("프롬프트 조회 API - 저장된 설정이 없으면 기본 프롬프트를 반환한다")
    void getPrompt_withoutSavedConfig_returnsDefaultPrompt() throws Exception {
        mockMvc.perform(get("/api/admin/prompt")
                        .header("Authorization", bearer(adminToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.systemPrompt", is(PromptConfigService.DEFAULT_SYSTEM_PROMPT)))
                .andExpect(jsonPath("$.data.id", nullValue()))
                .andExpect(jsonPath("$.data.updatedAt", nullValue()));
    }

    @Test
    @DisplayName("프롬프트 저장 API - ADMIN 권한으로 시스템 프롬프트를 저장한다")
    void updatePrompt_withAdminToken_savesPrompt() throws Exception {
        String requestJson = """
                {
                  "systemPrompt": "  학교 문서를 근거로 답변하고 모르면 모른다고 답한다.  "
                }
                """;

        mockMvc.perform(put("/api/admin/prompt")
                        .header("Authorization", bearer(adminToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(requestJson))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.systemPrompt", is("학교 문서를 근거로 답변하고 모르면 모른다고 답한다.")))
                .andExpect(jsonPath("$.data.updatedByUsername", is(ADMIN_USERNAME)))
                .andExpect(jsonPath("$.data.updatedAt").isNotEmpty());

        PromptConfig saved = promptConfigRepository.findFirstByOrderByUpdatedAtDescIdDesc().orElseThrow();
        assertEquals("학교 문서를 근거로 답변하고 모르면 모른다고 답한다.", saved.getSystemPrompt());
        assertNotNull(saved.getUpdatedAt());
        assertEquals(admin.getId(), saved.getUpdatedBy().getId());
    }

    @Test
    @DisplayName("프롬프트 저장 API - 빈 프롬프트는 400을 반환한다")
    void updatePrompt_blankPrompt_returns400() throws Exception {
        String requestJson = """
                {
                  "systemPrompt": "   "
                }
                """;

        mockMvc.perform(put("/api/admin/prompt")
                        .header("Authorization", bearer(adminToken()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(requestJson))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("프롬프트 API - 비인증 요청은 401을 반환한다")
    void promptApi_withoutToken_returns401() throws Exception {
        mockMvc.perform(get("/api/admin/prompt"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("프롬프트 API - USER 권한 요청은 403을 반환한다")
    void promptApi_userRole_returns403() throws Exception {
        String userToken = jwtProvider.generateToken("user", User.Role.USER.name(), 999L);

        mockMvc.perform(get("/api/admin/prompt")
                        .header("Authorization", bearer(userToken)))
                .andExpect(status().isForbidden());
    }

    // 테스트용 ADMIN Access Token을 생성한다.
    private String adminToken() {
        return jwtProvider.generateToken(admin.getUsername(), admin.getRole().name(), admin.getId());
    }

    // Authorization 헤더에 사용할 Bearer Token 값을 생성한다.
    private String bearer(String token) {
        return "Bearer " + token;
    }
}
