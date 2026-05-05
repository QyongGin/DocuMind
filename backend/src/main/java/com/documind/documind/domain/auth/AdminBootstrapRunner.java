package com.documind.documind.domain.auth;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

/**
 * 환경변수로 주입된 최초 관리자 계정을 생성하는 부트스트랩 컴포넌트.
 * 운영 비밀번호를 코드나 SQL 파일에 고정하지 않기 위해 username/password가 모두 있을 때만 동작한다.
 */
// @Component: 애플리케이션 시작 시 CommandLineRunner로 실행할 Spring Bean으로 등록한다.
@Component
@RequiredArgsConstructor
@Slf4j
public class AdminBootstrapRunner implements CommandLineRunner {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    @Value("${documind.admin.bootstrap.username:}")
    private String adminUsername;

    @Value("${documind.admin.bootstrap.password:}")
    private String adminPassword;

    /**
     * 최초 관리자 환경변수가 제공되면 계정을 생성한다.
     * 이미 같은 username이 존재하면 비밀번호를 덮어쓰지 않는다.
     */
    @Override
    @Transactional
    public void run(String... args) {
        if (!StringUtils.hasText(adminUsername) || !StringUtils.hasText(adminPassword)) {
            log.info("최초 관리자 계정 부트스트랩을 건너뜁니다. DOCUMIND_ADMIN_USERNAME/PASSWORD가 모두 필요합니다.");
            return;
        }

        if (userRepository.findByUsername(adminUsername).isPresent()) {
            log.info("최초 관리자 계정 부트스트랩을 건너뜁니다. username={} 계정이 이미 존재합니다.", adminUsername);
            return;
        }

        userRepository.save(User.create(
                adminUsername,
                passwordEncoder.encode(adminPassword),
                User.Role.ADMIN
        ));
        log.info("최초 관리자 계정을 생성했습니다. username={}", adminUsername);
    }
}
