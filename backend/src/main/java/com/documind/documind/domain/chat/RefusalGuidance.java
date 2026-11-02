package com.documind.documind.domain.chat;

/**
 * 거절 문장만 있는 답에 붙이는 정해 둔 안내(ADR-0050 결정 3). 문구와 주소는 설정 `chat.answer.*`에 둔다.
 *
 * @param retryHint    다시 묻는 방법(예: 학과, 학년도, 학기를 넣어 다시 질문하기)
 * @param contactLabel 문의처 안내 이름(예: 교내 전화번호 안내)
 * @param contactUrl   문의처 안내 주소
 */
public record RefusalGuidance(String retryHint, String contactLabel, String contactUrl) {
}
