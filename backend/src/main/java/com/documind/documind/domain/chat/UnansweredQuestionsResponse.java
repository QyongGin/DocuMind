package com.documind.documind.domain.chat;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 관리자 '못 답한 질문' 목록 한 쪽(ADR-0052 결정 5). 거절 문장만 나간 답의 질문을 최근 것부터 담는다.
 *
 * @param items 이 쪽의 질문
 * @param total 전체 질문 수
 * @param page  쪽 번호(0부터)
 * @param size  쪽 크기
 */
public record UnansweredQuestionsResponse(List<Item> items, long total, int page, int size) {

    /**
     * 못 답한 질문 하나. messageId로 개발자 정보를 연다.
     *
     * @param messageId 답(메시지) ID
     * @param question  사용자 질문
     * @param askedAt   질문 시각
     */
    public record Item(Long messageId, String question, LocalDateTime askedAt) {
    }
}
