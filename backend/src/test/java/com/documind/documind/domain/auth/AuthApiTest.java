package com.documind.documind.domain.auth;

import com.documind.documind.global.auth.JwtProvider;
import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validator;
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

import java.util.Set;

import jakarta.servlet.http.Cookie;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.hamcrest.Matchers.containsString;

/**
 * 인증 API 서비스 레이어 통합 테스트.
 * FastApiClient는 @MockitoBean으로 대체해 외부 HTTP 호출을 격리한다.
 */
// @SpringBootTest: 전체 애플리케이션 컨텍스트를 로드해 실제 DB(H2 인메모리) 기반으로 검증한다.
// @AutoConfigureMockMvc: Spring Security 필터 체인을 포함한 MVC 요청 테스트를 활성화한다.
// @ActiveProfiles: 테스트 전용 application-test.yaml 설정을 로드한다.
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class AuthApiTest {

    @Autowired
    private AuthService authService;

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    private JwtProvider jwtProvider;

    @Autowired
    private Validator validator;

    // FastApiClient Bean이 컨텍스트에 등록되어 있어 Mock으로 대체해야 컨텍스트 로딩이 성공한다
    @MockitoBean
    private FastApiClient fastApiClient;

    // 테스트에서 공통으로 사용할 실제 비밀번호 (평문)
    // BCrypt 검증이 실제로 동작하므로 passwordEncoder.encode()로 저장해야 한다
    private static final String RAW_PASSWORD = "admin1234";
    private static final String ADMIN_USERNAME = "admin";
    private static final String PASSWORD_CHANGE_JSON = """
            {
              "currentPassword": "admin1234",
              "newPassword": "newPassword123"
            }
            """;

    @BeforeEach
    void setUp() {
        String encoded = passwordEncoder.encode(RAW_PASSWORD);
        userRepository.save(User.create(ADMIN_USERNAME, encoded, User.Role.ADMIN));
    }

    @AfterEach
    void tearDown() {
        userRepository.deleteAll();
    }

    @Test
    @DisplayName("로그인 - Access Token을 발급하고 Refresh Token은 DB와 HttpOnly 쿠키로 관리한다")
    void login_success() {
        LoginResponse response = authService.login(ADMIN_USERNAME, RAW_PASSWORD);

        assertNotNull(response.getAccessToken());
        // refreshToken은 JSON 직렬화 대상이 아니지만 서비스 레이어에서는 정상 생성된다
        assertNotNull(response.getRefreshToken());

        // DB에 Refresh Token이 저장됐는지 확인
        User saved = userRepository.findByUsername(ADMIN_USERNAME).orElseThrow();
        assertEquals(response.getRefreshToken(), saved.getRefreshToken());
        assertNotNull(saved.getLastLoginAt());
    }

    @Test
    @DisplayName("로그인 API - 응답 body에 accessToken이 있고 Set-Cookie에 refresh-token이 존재한다")
    void loginApi_setsRefreshTokenCookie() throws Exception {
        String loginJson = String.format("""
                { "username": "%s", "password": "%s" }
                """, ADMIN_USERNAME, RAW_PASSWORD);

        mockMvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(loginJson))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.accessToken").isNotEmpty())
                // refreshToken은 body에 노출되지 않아야 한다
                .andExpect(jsonPath("$.data.refreshToken").doesNotExist())
                .andExpect(header().string("Set-Cookie", containsString("refresh-token=")))
                .andExpect(header().string("Set-Cookie", containsString("HttpOnly")))
                .andExpect(header().string("Set-Cookie", containsString("SameSite=Strict")))
                .andExpect(header().string("Set-Cookie", containsString("Path=/api/auth")));
    }

    @Test
    @DisplayName("토큰 재발급 API - refresh-token 쿠키로 새 Access Token을 발급한다")
    void reissueApi_withCookie_returnsNewAccessToken() throws Exception {
        LoginResponse loginResponse = authService.login(ADMIN_USERNAME, RAW_PASSWORD);

        mockMvc.perform(post("/api/auth/reissue")
                        .cookie(new Cookie("refresh-token", loginResponse.getRefreshToken())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").isNotEmpty());
    }

    @Test
    @DisplayName("토큰 재발급 API - refresh-token 쿠키 없이 요청하면 401을 반환한다")
    void reissueApi_withoutCookie_returns401() throws Exception {
        mockMvc.perform(post("/api/auth/reissue"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("로그인 - 잘못된 비밀번호는 INVALID_CREDENTIALS 예외를 반환한다")
    void login_wrongPassword() {
        CustomException ex = assertThrows(CustomException.class,
                () -> authService.login(ADMIN_USERNAME, "wrong-password"));

        assertEquals(ErrorCode.INVALID_CREDENTIALS, ex.getErrorCode());
    }

    @Test
    @DisplayName("로그인 - 존재하지 않는 사용자명은 INVALID_CREDENTIALS 예외를 반환한다")
    void login_wrongUsername() {
        CustomException ex = assertThrows(CustomException.class,
                () -> authService.login("nobody", RAW_PASSWORD));

        assertEquals(ErrorCode.INVALID_CREDENTIALS, ex.getErrorCode());
    }

    @Test
    @DisplayName("로그아웃 - DB의 Refresh Token이 null로 초기화된다")
    void logout_clearsRefreshToken() {
        // 로그인으로 Refresh Token을 DB에 저장한 뒤 로그아웃
        authService.login(ADMIN_USERNAME, RAW_PASSWORD);
        authService.logout(ADMIN_USERNAME);

        User saved = userRepository.findByUsername(ADMIN_USERNAME).orElseThrow();
        assertNull(saved.getRefreshToken());
    }

    @Test
    @DisplayName("로그아웃 API - Access Token 없이 refresh-token 쿠키만 있어도 DB 토큰 제거와 쿠키 만료를 수행한다")
    void logoutApi_withRefreshCookieOnly_clearsRefreshTokenAndExpiresCookie() throws Exception {
        LoginResponse loginResponse = authService.login(ADMIN_USERNAME, RAW_PASSWORD);

        mockMvc.perform(post("/api/auth/logout")
                        .cookie(new Cookie("refresh-token", loginResponse.getRefreshToken())))
                .andExpect(status().isOk())
                .andExpect(header().string("Set-Cookie", containsString("refresh-token=")))
                .andExpect(header().string("Set-Cookie", containsString("Max-Age=0")))
                .andExpect(header().string("Set-Cookie", containsString("Path=/api/auth")));

        User saved = userRepository.findByUsername(ADMIN_USERNAME).orElseThrow();
        assertNull(saved.getRefreshToken());
    }

    @Test
    @DisplayName("로그아웃 API - 토큰이 없어도 HttpOnly 쿠키 만료 응답은 반환한다")
    void logoutApi_withoutTokens_returnsCookieExpiration() throws Exception {
        mockMvc.perform(post("/api/auth/logout"))
                .andExpect(status().isOk())
                .andExpect(header().string("Set-Cookie", containsString("refresh-token=")))
                .andExpect(header().string("Set-Cookie", containsString("Max-Age=0")));
    }

    @Test
    @DisplayName("토큰 재발급 - 유효한 Refresh Token으로 새 Access Token을 반환한다")
    void reissue_success() {
        LoginResponse loginResponse = authService.login(ADMIN_USERNAME, RAW_PASSWORD);

        String newAccessToken = authService.reissue(loginResponse.getRefreshToken());

        assertNotNull(newAccessToken);
        assertTrue(jwtProvider.validateToken(newAccessToken));
        assertEquals(ADMIN_USERNAME, jwtProvider.getUsername(newAccessToken));
    }

    @Test
    @DisplayName("토큰 재발급 - 유효하지 않은 Refresh Token은 INVALID_TOKEN 예외를 반환한다")
    void reissue_invalidToken() {
        CustomException ex = assertThrows(CustomException.class,
                () -> authService.reissue("invalid.token.value"));

        assertEquals(ErrorCode.INVALID_TOKEN, ex.getErrorCode());
    }

    @Test
    @DisplayName("비밀번호 변경 - 현재 비밀번호 일치 시 변경되고 기존 토큰과 비밀번호가 무효화된다")
    void changePassword_success() {
        String newPassword = "newPassword123";
        LoginResponse oldLoginResponse = authService.login(ADMIN_USERNAME, RAW_PASSWORD);

        authService.changePassword(ADMIN_USERNAME, RAW_PASSWORD, newPassword);

        // 비밀번호 변경 직후 기존 Refresh Token을 DB에서 제거해 재발급을 차단한다
        User afterChange = userRepository.findByUsername(ADMIN_USERNAME).orElseThrow();
        assertNull(afterChange.getRefreshToken());

        CustomException reissueEx = assertThrows(CustomException.class,
                () -> authService.reissue(oldLoginResponse.getRefreshToken()));
        assertEquals(ErrorCode.INVALID_TOKEN, reissueEx.getErrorCode());

        // 이전 비밀번호로 로그인 실패 검증
        CustomException loginEx = assertThrows(CustomException.class,
                () -> authService.login(ADMIN_USERNAME, RAW_PASSWORD));
        assertEquals(ErrorCode.INVALID_CREDENTIALS, loginEx.getErrorCode());

        // 새 비밀번호로 로그인 성공 여부로 실제 변경을 검증
        LoginResponse response = authService.login(ADMIN_USERNAME, newPassword);
        assertNotNull(response.getAccessToken());
    }

    @Test
    @DisplayName("비밀번호 변경 API - 비인증 요청은 401을 반환한다")
    void changePasswordApi_unauthenticated_returns401() throws Exception {
        mockMvc.perform(post("/api/auth/password")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(PASSWORD_CHANGE_JSON))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("비밀번호 변경 API - USER 권한 요청은 403을 반환한다")
    void changePasswordApi_userRole_returns403() throws Exception {
        String userToken = jwtProvider.generateToken("user", User.Role.USER.name(), 999L);

        mockMvc.perform(post("/api/auth/password")
                        .header("Authorization", bearer(userToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(PASSWORD_CHANGE_JSON))
                .andExpect(status().isForbidden());
    }

    @Test
    @DisplayName("비밀번호 변경 API - ADMIN 권한 요청은 200을 반환한다")
    void changePasswordApi_adminRole_returns200() throws Exception {
        User admin = userRepository.findByUsername(ADMIN_USERNAME).orElseThrow();
        String adminToken = jwtProvider.generateToken(admin.getUsername(), admin.getRole().name(), admin.getId());

        mockMvc.perform(post("/api/auth/password")
                        .header("Authorization", bearer(adminToken))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(PASSWORD_CHANGE_JSON))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("비밀번호 변경 요청 - 새 비밀번호가 8자 미만이면 검증 실패한다")
    void changePasswordRequest_shortNewPassword() {
        PasswordChangeRequest request = new PasswordChangeRequest(RAW_PASSWORD, "short");

        Set<ConstraintViolation<PasswordChangeRequest>> violations = validator.validate(request);

        assertTrue(violations.stream()
                .anyMatch(v -> "새 비밀번호는 최소 8자 이상이어야 합니다.".equals(v.getMessage())));
    }

    @Test
    @DisplayName("비밀번호 변경 - 현재 비밀번호 불일치 시 WRONG_PASSWORD 예외를 반환한다")
    void changePassword_wrongCurrentPassword() {
        CustomException ex = assertThrows(CustomException.class,
                () -> authService.changePassword(ADMIN_USERNAME, "wrongCurrent", "newPassword123"));

        assertEquals(ErrorCode.WRONG_PASSWORD, ex.getErrorCode());
    }

    // Authorization 헤더에 사용할 Bearer Token 값을 생성한다
    private String bearer(String token) {
        return "Bearer " + token;
    }
}
