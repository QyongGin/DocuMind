package com.documind.documind.domain.chat;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 관리자 개발자 모드의 답 하나 정보(ADR-0050 결정 6, ADR-0052, docs/project/챗봇-답변-형식.md §4).
 *
 * @param messageId        답(메시지) ID
 * @param question         사용자 질문
 * @param createdAt        질문 시각
 * @param rawAnswer        모델 원문 답(출처 번호 포함)
 * @param answer           화면에 보낸 답
 * @param citedSources     답이 쓴 근거 번호(화면에서 지운 출처 번호)
 * @param guidanceAttached 거절 문장만 나가 정해 둔 안내를 붙였는지
 * @param sources          근거 후보. N번째가 프롬프트의 [출처 N]이다
 * @param trace            처리 기록(프롬프트, 단계별 걸린 초, 후보별 검색 점수, 모델 설정). 보관 기간이 지났거나 없으면 null
 */
public record ChatDevInfoResponse(
        Long messageId,
        String question,
        LocalDateTime createdAt,
        String rawAnswer,
        String answer,
        List<Integer> citedSources,
        boolean guidanceAttached,
        List<Map<String, Object>> sources,
        Map<String, Object> trace
) {
}
