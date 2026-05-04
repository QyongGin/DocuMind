package com.documind.documind.global.auth;

import io.jsonwebtoken.*;
import io.jsonwebtoken.security.Keys;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Date;

/** JWT 토큰 생성, 파싱, 검증을 담당하는 컴포넌트 */
// @Component: 스프링 빈으로 등록
@Component
public class JwtProvider {

    // application.yaml의 jwt.secret 값을 주입
    @Value("${jwt.secret}")
    private String secret;

    // application.yaml의 jwt.access-token-expiration 값을 주입
    @Value("${jwt.access-token-expiration}")
    private Duration accessTokenExpiration;

    // application.yaml의 jwt.refresh-token-expiration 값을 주입
    @Value("${jwt.refresh-token-expiration}")
    private Duration refreshTokenExpiration;

    private SecretKey key;

    // @PostConstruct: 빈 생성 후 의존성 주입이 완료된 시점에 실행. secret으로 서명 키를 초기화
    @PostConstruct
    protected void init() {
        this.key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
    }

    /** username, role, userId를 담아 JWT를 생성한다. userId는 채팅 세션 소유권 검증에 사용한다. */
    public String generateToken(String username, String role, Long userId) {
        Date now = new Date();
        return Jwts.builder()
                .subject(username)
                .claim("role", role)
                .claim("userId", userId)
                .issuedAt(now)
                .expiration(new Date(now.getTime() + accessTokenExpiration.toMillis()))
                .signWith(key)
                .compact();
    }

    /** username만 담아 Refresh Token을 생성한다. role 정보는 포함하지 않는다. */
    public String generateRefreshToken(String username) {
        Date now = new Date();
        return Jwts.builder()
                .subject(username)
                .issuedAt(now)
                .expiration(new Date(now.getTime() + refreshTokenExpiration.toMillis()))
                .signWith(key)
                .compact();
    }

    /** JWT에서 username(subject)을 추출한다. */
    public String getUsername(String token) {
        return parseClaims(token).getSubject();
    }

    /** JWT에서 role 클레임을 추출한다. */
    public String getRole(String token) {
        return parseClaims(token).get("role", String.class);
    }

    /** JWT에서 userId 클레임을 추출한다. DB 조회 없이 채팅 세션 소유권 검증에 사용한다. */
    public Long getUserId(String token) {
        return parseClaims(token).get("userId", Long.class);
    }

    /** JWT 유효성을 검증한다. 만료되거나 서명이 잘못된 경우 false를 반환한다. */
    public boolean validateToken(String token) {
        try {
            parseClaims(token);
            return true;
        } catch (JwtException | IllegalArgumentException e) {
            return false;
        }
    }

    // JWT를 파싱해 Claims를 반환. 서명 검증 포함
    private Claims parseClaims(String token) {
        return Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }
}
