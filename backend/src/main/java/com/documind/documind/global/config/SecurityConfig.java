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

// Spring Security 전역 설정 클래스
// @Configuration: 스프링 설정 클래스임을 선언
// @EnableWebSecurity: Spring Security 활성화
@Configuration
@EnableWebSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    private final JwtProvider jwtProvider;
    private final AuthEntryPoint authEntryPoint;
    private final AccessDeniedHandlerImpl accessDeniedHandler;

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
            // 경로별 접근 권한 설정
            .authorizeHttpRequests(auth -> auth
                    // 관리자 전용 경로: ADMIN 권한 필요
                    .requestMatchers("/api/admin/**").hasRole("ADMIN")
                    // 문서 업로드·목록·삭제는 ADMIN 전용
                    .requestMatchers(HttpMethod.GET, "/api/documents").hasRole("ADMIN")
                    .requestMatchers(HttpMethod.POST, "/api/documents").hasRole("ADMIN")
                    .requestMatchers(HttpMethod.DELETE, "/api/documents/**").hasRole("ADMIN")
                    // 카테고리 생성은 ADMIN 전용, 목록 조회는 anyRequest().permitAll()로 허용
                    .requestMatchers(HttpMethod.POST, "/api/categories").hasRole("ADMIN")
                    // 로그인 엔드포인트: 인증 없이 접근 허용
                    .requestMatchers("/api/auth/login").permitAll()
                    // 나머지: USER는 로그인 불필요이므로 전체 허용
                    .anyRequest().permitAll()
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

    // Vite dev server(5173), Docker nginx(80), nginx 기본 포트(80)에서의 브라우저 요청 허용
    @Bean
    CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOrigins(List.of("http://localhost:5173", "http://localhost:80", "http://localhost"));
        config.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        // EventSource(SSE) 쿠키 기반 세션 추적을 위해 credentials 허용
        config.setAllowCredentials(true);
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }

    // BCrypt 해시 알고리즘으로 비밀번호를 암호화. 스프링 빈으로 등록해 어디서든 주입 가능
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
