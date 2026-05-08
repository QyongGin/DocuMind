package com.documind.documind.domain.admin;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

/**
 * 프롬프트 설정 Entity의 저장과 최신 설정 조회를 담당하는 Repository이다.
 */
public interface PromptConfigRepository extends JpaRepository<PromptConfig, Long> {

    /**
     * 가장 최근에 수정된 프롬프트 설정을 조회한다.
     *
     * @return 최신 프롬프트 설정. 아직 저장된 설정이 없으면 empty
     */
    Optional<PromptConfig> findFirstByOrderByUpdatedAtDescIdDesc();
}
