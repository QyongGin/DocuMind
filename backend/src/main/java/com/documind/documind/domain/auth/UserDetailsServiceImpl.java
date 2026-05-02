package com.documind.documind.domain.auth;

import lombok.RequiredArgsConstructor;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;

import java.util.List;

// Spring Security가 로그인 처리 시 호출하는 사용자 조회 서비스
// @Service: 스프링 빈으로 등록
@Service
// @RequiredArgsConstructor: final 필드를 인자로 받는 생성자를 자동 생성 (Lombok)
@RequiredArgsConstructor
public class UserDetailsServiceImpl implements UserDetailsService {

    private final UserRepository userRepository;

    // Spring Security가 인증 처리 시 호출하는 메서드. username으로 DB에서 사용자를 조회
    @Override
    public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new UsernameNotFoundException("사용자를 찾을 수 없습니다: " + username));

        // ROLE_ 접두사를 붙여 Spring Security의 권한 형식에 맞춤 (예: ROLE_ADMIN)
        return new org.springframework.security.core.userdetails.User(
                user.getUsername(),
                user.getPassword(),
                List.of(new SimpleGrantedAuthority("ROLE_" + user.getRole().name()))
        );
    }
}