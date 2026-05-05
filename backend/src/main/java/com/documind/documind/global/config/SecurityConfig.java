package com.documind.documind.global.config;

import com.documind.documind.global.auth.AccessDeniedHandlerImpl;
import com.documind.documind.global.auth.AuthEntryPoint;
import com.documind.documind.global.auth.JwtAuthenticationFilter;
import com.documind.documind.global.auth.JwtProvider;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.util.List;

/**
 * Spring Security 전역 설정 클래스.
 * JWT 기반 stateless 인증, CORS, 경로별 인가 정책을 정의한다.
 */
// @Configuration: 스프링 설정 클래스임을 선언
// @EnableWebSecurity: Spring Security 활성화
@Configuration
@EnableWebSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    private final JwtProvider jwtProvider;
    private final AuthEntryPoint authEntryPoint;
    private final AccessDeniedHandlerImpl accessDeniedHandler;

    /**
     * HTTP 보안 필터 체인을 구성한다.
     * 관리자 전용 API는 ADMIN 권한을 요구하고, 사용자 채팅 API는 비로그인 접근을 허용한다.
     */
    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            // EventSource(SSE)는 브라우저가 CORS 요청으로 전송하므로 반드시 CORS 설정이 선행되어야 한다
            .cors(cors -> cors.configurationSource(corsConfigurationSource()))
            // REST API는 CSRF 공격 대상이 아니므로 비활성화
            .csrf(AbstractHttpConfigurer::disable)
            // JWT 사용으로 세션이 필요 없으므로 STATELESS로 설정
            .sessionManagement(session ->
                    session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            // 경로별 접근 권한 설정 — default-deny 정책: 명시하지 않은 경로는 자동 차단
            .authorizeHttpRequests(auth -> auth
                    // ADMIN 전용
                    .requestMatchers("/api/admin/**").hasRole("ADMIN")
                    .requestMatchers(HttpMethod.GET, "/api/documents").hasRole("ADMIN")
                    .requestMatchers(HttpMethod.POST, "/api/documents").hasRole("ADMIN")
                    .requestMatchers(HttpMethod.DELETE, "/api/documents/**").hasRole("ADMIN")
                    .requestMatchers(HttpMethod.POST, "/api/categories").hasRole("ADMIN")
                    .requestMatchers(HttpMethod.POST, "/api/auth/password").hasRole("ADMIN")

                    // 인증된 사용자 전용
                    // 로그아웃은 DB의 Refresh Token을 제거하므로 인증된 사용자만 호출할 수 있다
                    .requestMatchers(HttpMethod.POST, "/api/auth/logout").authenticated()

                    // 공개 — USER 비로그인 허용
                    .requestMatchers(HttpMethod.POST, "/api/auth/login", "/api/auth/reissue").permitAll()
                    .requestMatchers(HttpMethod.GET, "/api/categories").permitAll()
                    .requestMatchers(HttpMethod.POST, "/api/chat").permitAll()
                    .requestMatchers(HttpMethod.GET, "/api/chat/stream").permitAll()
                    .requestMatchers(HttpMethod.GET, "/api/chat/sessions").permitAll()
                    .requestMatchers(HttpMethod.GET, "/api/chat/sessions/**").permitAll()
                    .requestMatchers(HttpMethod.DELETE, "/api/chat/sessions/**").permitAll()
                    .requestMatchers("/error", "/actuator/health").permitAll()

                    // 명시되지 않은 모든 요청 차단 — 새 API 추가 시 반드시 위에 명시해야 한다
                    .anyRequest().denyAll()
            )
            // 인증/권한 예외 처리 핸들러 등록
            .exceptionHandling(ex -> ex
                    .authenticationEntryPoint(authEntryPoint)
                    .accessDeniedHandler(accessDeniedHandler)
            )
            // JWT 필터를 UsernamePasswordAuthenticationFilter 앞에 등록
            .addFilterBefore(
                    new JwtAuthenticationFilter(jwtProvider),
                    UsernamePasswordAuthenticationFilter.class
            );

        return http.build();
    }

    // Vite dev server(5173), Docker nginx(80), 운영 서버(192.168.35.168)에서의 브라우저 요청 허용
    // allowCredentials(true)와 allowedOrigins("*") 조합은 Spring CORS에서 예외 발생 — origin 명시 필수
    @Bean
    CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOrigins(List.of(
                "http://localhost:5173",
                "http://localhost",
                "http://192.168.35.168"  // 운영 서버 — HttpOnly cookie 및 SSE credentials 요청 허용
        ));
        config.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        // HttpOnly cookie(refresh-token)와 SSE EventSource credentials 전송을 위해 true로 설정
        config.setAllowCredentials(true);
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }

    /**
     * BCrypt 해시 알고리즘으로 비밀번호를 암호화하는 PasswordEncoder Bean을 등록한다.
     */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
