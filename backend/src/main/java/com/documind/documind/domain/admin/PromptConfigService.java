package com.documind.documind.domain.admin;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 관리자 프롬프트 설정 조회와 저장 비즈니스 로직을 담당한다.
 */
@Service
@RequiredArgsConstructor
public class PromptConfigService {

    public static final String DEFAULT_SYSTEM_PROMPT =
            "인하공업전문대학 홈페이지와 학사 안내 문서에 근거해서 간결하고 정확하게 답변한다.";

    private final PromptConfigRepository promptConfigRepository;
    private final UserRepository userRepository;

    /**
     * 최신 프롬프트 설정을 조회한다. 저장된 설정이 없으면 기본 프롬프트를 반환한다.
     *
     * @return 최신 프롬프트 설정 또는 기본 프롬프트 응답
     */
    @Transactional(readOnly = true)
    public PromptConfigResponse getCurrent() {
        return promptConfigRepository.findFirstByOrderByUpdatedAtDescIdDesc()
                .map(PromptConfigResponse::from)
                .orElseGet(this::defaultResponse);
    }

    /**
     * 프롬프트 설정을 저장한다. 기존 설정이 있으면 최신 행을 갱신하고, 없으면 새 행을 만든다.
     *
     * @param request  저장할 시스템 프롬프트 요청 DTO
     * @param username 설정을 저장한 관리자 계정명
     * @return 저장된 프롬프트 설정 응답
     * @throws CustomException 관리자 계정을 찾을 수 없는 경우 USER_NOT_FOUND
     */
    @Transactional
    public PromptConfigResponse update(PromptConfigRequest request, String username) {
        User updater = userRepository.findByUsername(username)
                .orElseThrow(() -> new CustomException(ErrorCode.USER_NOT_FOUND));
        String systemPrompt = request.getSystemPrompt().trim();

        PromptConfig config = promptConfigRepository.findFirstByOrderByUpdatedAtDescIdDesc()
                .map(existing -> updateExisting(existing, systemPrompt, updater))
                .orElseGet(() -> promptConfigRepository.save(PromptConfig.create(systemPrompt, updater)));

        return PromptConfigResponse.from(config);
    }

    // 기존 설정 갱신을 Optional.map에서 사용하기 위한 작은 helper이다.
    private PromptConfig updateExisting(PromptConfig config, String systemPrompt, User updater) {
        config.update(systemPrompt, updater);
        return config;
    }

    // DB에 저장된 설정이 없을 때 화면에 보여줄 기본 프롬프트 응답이다.
    private PromptConfigResponse defaultResponse() {
        return PromptConfigResponse.builder()
                .id(null)
                .systemPrompt(DEFAULT_SYSTEM_PROMPT)
                .updatedByUsername(null)
                .updatedAt(null)
                .build();
    }
}
