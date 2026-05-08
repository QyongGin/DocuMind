package com.documind.documind.domain.admin;

import com.documind.documind.domain.auth.User;
import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * LLM 답변 생성에 사용할 관리자 설정 프롬프트를 저장하는 Entity이다.
 */
@Entity
// 매핑할 테이블 이름 지정
@Table(name = "prompt_config")
// 모든 필드의 getter 메서드 자동 생성 (Lombok)
@Getter
// 기본 생성자 자동 생성, PROTECTED로 설정해 외부에서 직접 new PromptConfig() 못하게 막음
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class PromptConfig {

    // PK 지정
    @Id
    // AUTO_INCREMENT (DB가 값을 자동 증가시킴)
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // LLM에 전달하는 시스템 프롬프트 본문. NOT NULL, TEXT 타입으로 길이 제한 없음
    @Column(nullable = false, columnDefinition = "TEXT")
    private String systemPrompt;

    // users 테이블과의 N:1 관계. 마지막으로 프롬프트를 수정한 관리자
    @ManyToOne(fetch = FetchType.LAZY)
    // FK 컬럼명 지정. nullable=false: 프롬프트는 반드시 관리자가 수정해야 함
    @JoinColumn(name = "updated_by", nullable = false)
    private User updatedBy;

    // prompt_config는 updated_at 적용 대상. 프롬프트 내용 수정 시 갱신
    @Column(nullable = false)
    private LocalDateTime updatedAt;

    // DB에 INSERT 되기 직전에 자동 실행되는 메서드
    @PrePersist
    protected void onCreate() {
        this.updatedAt = LocalDateTime.now();
    }

    // DB에 UPDATE 되기 직전에 자동 실행되는 메서드
    @PreUpdate
    protected void onUpdate() {
        this.updatedAt = LocalDateTime.now();
    }

    /**
     * 새 프롬프트 설정을 생성한다.
     *
     * @param systemPrompt LLM에 전달할 시스템 프롬프트
     * @param updatedBy    설정을 저장한 관리자
     * @return 저장 전 프롬프트 설정 Entity
     */
    public static PromptConfig create(String systemPrompt, User updatedBy) {
        PromptConfig config = new PromptConfig();
        config.systemPrompt = systemPrompt;
        config.updatedBy = updatedBy;
        return config;
    }

    /**
     * 기존 프롬프트 설정 내용을 변경하고 마지막 수정 관리자를 갱신한다.
     *
     * @param systemPrompt 새 시스템 프롬프트
     * @param updatedBy    설정을 저장한 관리자
     */
    public void update(String systemPrompt, User updatedBy) {
        this.systemPrompt = systemPrompt;
        this.updatedBy = updatedBy;
        this.updatedAt = LocalDateTime.now();
    }
}
