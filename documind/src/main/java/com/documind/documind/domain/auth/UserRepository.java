package com.documind.documind.domain.auth;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

// JpaRepository를 상속받아 기본 CRUD 메서드를 자동으로 제공
public interface UserRepository extends JpaRepository<User, Long> {

    // username으로 사용자를 조회. 로그인 시 사용
    Optional<User> findByUsername(String username);
}
