package com.documind.documind.domain.auth;

import com.documind.documind.global.auth.JwtProvider;
import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

// 로그인, 로그아웃, 토큰 재발급 비즈니스 로직을 담당
// @Service: 스프링 빈으로 등록
// @RequiredArgsConstructor: final 필드를 인자로 받는 생성자를 자동 생성 (Lombok)
@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtProvider jwtProvider;

    // 로그인: username/password 검증 후 Access Token과 Refresh Token을 발급
    // @Transactional: 메서드 실행 전 트랜잭션을 시작하고, 정상 종료 시 커밋, 예외 발생 시 롤백
    @Transactional
    public LoginResponse login(String username, String password) {
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new CustomException(ErrorCode.INVALID_CREDENTIALS));

        // DB에 저장된 BCrypt 해시와 입력한 평문 비밀번호를 비교
        if (!passwordEncoder.matches(password, user.getPassword())) {
            throw new CustomException(ErrorCode.INVALID_CREDENTIALS);
        }

        String accessToken = jwtProvider.generateToken(user.getUsername(), user.getRole().name(), user.getId());
        String refreshToken = jwtProvider.generateRefreshToken(user.getUsername());

        // Refresh Token 저장 및 마지막 로그인 시각 갱신
        user.login(refreshToken);

        return LoginResponse.builder()
                .accessToken(accessToken)
                .refreshToken(refreshToken)
                .build();
    }

    // 로그아웃: DB의 Refresh Token을 NULL로 초기화하여 재사용 차단
    @Transactional
    public void logout(String username) {
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new CustomException(ErrorCode.USER_NOT_FOUND));
        user.logout();
    }

    /**
     * 비밀번호를 변경한다.
     * currentPassword를 재확인하는 이유: Access Token이 유효해도 세션 탈취 공격자가
     * 비밀번호를 바꿔버리는 것을 막기 위해 본인 의사 확인이 필요하다.
     * @throws CustomException WRONG_PASSWORD — 현재 비밀번호 불일치
     * @throws CustomException USER_NOT_FOUND — 사용자 미존재 (정상 흐름에서는 발생하지 않음)
     */
    @Transactional
    public void changePassword(String username, String currentPassword, String newPassword) {
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new CustomException(ErrorCode.USER_NOT_FOUND));

        if (!passwordEncoder.matches(currentPassword, user.getPassword())) {
            throw new CustomException(ErrorCode.WRONG_PASSWORD);
        }

        user.changePassword(passwordEncoder.encode(newPassword));
    }

    // Access Token 재발급: Refresh Token 유효성 검증 후 새로운 Access Token 발급
    @Transactional
    public String reissue(String refreshToken) {
        if (!jwtProvider.validateToken(refreshToken)) {
            throw new CustomException(ErrorCode.INVALID_TOKEN);
        }

        User user = userRepository.findByRefreshToken(refreshToken)
                .orElseThrow(() -> new CustomException(ErrorCode.INVALID_TOKEN));

        return jwtProvider.generateToken(user.getUsername(), user.getRole().name(), user.getId());
    }
}
