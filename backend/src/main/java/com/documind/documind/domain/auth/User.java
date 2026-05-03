package com.documind.documind.domain.auth;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

// DB의 users 테이블과 매핑되는 Entity 클래스임을 선언
@Entity
// 매핑할 테이블 이름 지정 (생략하면 클래스명 그대로 사용)
@Table(name = "users")
// 모든 필드의 getter 메서드 자동 생성 (Lombok)
@Getter
// 기본 생성자 자동 생성, PROTECTED로 설정해 외부에서 직접 new User() 못하게 막음
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class User {

    // PK 지정
    @Id
    // AUTO_INCREMENT (DB가 값을 자동 증가시킴)
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // NOT NULL, UNIQUE, 최대 길이 50
    @Column(nullable = false, unique = true, length = 50)
    private String username;

    @Column(nullable = false)
    private String password;

    // Enum을 DB에 문자열(STRING)로 저장. 숫자(ORDINAL)로 저장하면 순서 바뀔 때 위험해서 STRING 사용
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Role role;

    @Column(nullable = false)
    private Boolean isActive = true;

    // Refresh Token 저장. 로그아웃 시 NULL로 초기화하여 무효화
    @Column(length = 512)
    private String refreshToken;

    // NULL 허용 (로그인 전에는 값 없음)
    private LocalDateTime lastLoginAt;

    // NOT NULL, updatable=false: 최초 저장 후 변경 불가
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    // 로그인 시 Refresh Token 저장 및 마지막 로그인 시각 갱신
    public void login(String refreshToken) {
        this.refreshToken = refreshToken;
        this.lastLoginAt = LocalDateTime.now();
    }

    // 로그아웃 시 Refresh Token을 NULL로 초기화하여 재사용 차단
    public void logout() {
        this.refreshToken = null;
    }

    /**
     * 비밀번호를 변경한다.
     * @param encodedNewPassword BCrypt 등으로 인코딩된 새 비밀번호. 호출 전 서비스 레이어에서 인코딩해야 한다.
     */
    public void changePassword(String encodedNewPassword) {
        this.password = encodedNewPassword;
    }

    // DB에 INSERT 되기 직전에 자동 실행되는 메서드
    @PrePersist
    protected void onCreate() {
        this.createdAt = LocalDateTime.now();
    }

    /**
     * User 인스턴스를 생성하는 팩토리 메서드.
     * @param encodedPassword BCrypt 등으로 인코딩된 비밀번호
     */
    public static User create(String username, String encodedPassword, Role role) {
        User user = new User();
        user.username = username;
        user.password = encodedPassword;
        user.role = role;
        user.isActive = true;
        return user;
    }

    // User 클래스 안에 Role Enum 정의
    public enum Role {
        ADMIN, USER
    }
}