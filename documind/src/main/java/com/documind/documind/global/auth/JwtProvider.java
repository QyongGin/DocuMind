package com.documind.documind.global.auth;

import io.jsonwebtoken.*;
import io.jsonwebtoken.security.Keys;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;

// JWT 토큰 생성, 파싱, 검증을 담당하는 컴포넌트
// @Component: 스프링 빈으로 등록
@Component
public class JwtProvider {

    // application.yaml의 jwt.secret 값을 주입
    @Value("${jwt.secret}")
    private String secret;

    // application.yaml의 jwt.expiration 값을 주입 (ms 단위)
    @Value("${jwt.expiration}")
    private long expiration;

    @Value("${jwt.refresh-expiration}")
    private long refreshExpiration;

    private SecretKey key;

    // @PostConstruct: 빈 생성 후 의존성 주입이 완료된 시점에 실행. secret으로 서명 키를 초기화
    @PostConstruct
    protected void init() {
        this.key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
    }

    // username과 role을 담아 JWT를 생성
    public String generateToken(String username, String role) {
        Date now = new Date();
        return Jwts.builder()
                .subject(username)
                .claim("role", role)
                .issuedAt(now)
                .expiration(new Date(now.getTime() + expiration))
                .signWith(key)
                .compact();
    }

    // username만 담아 Refresh Token을 생성. role 정보는 포함하지 않음
    public String generateRefreshToken(String username) {
        Date now = new Date();
        return Jwts.builder()
                .subject(username)
                .issuedAt(now)
                .expiration(new Date(now.getTime() + refreshExpiration))
                .signWith(key)
                .compact();
    }

    // JWT에서 username(subject)을 추출
    public String getUsername(String token) {
        return parseClaims(token).getSubject();
    }

    // JWT에서 role 클레임을 추출
    public String getRole(String token) {
        return parseClaims(token).get("role", String.class);
    }

    // JWT 유효성 검증. 만료되거나 서명이 잘못된 경우 false 반환
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