package com.documind.documind.domain.chat;

/**
 * 화면용 답 속 링크 하나(ADR-0050 결정 5). 화면은 답 글의 [start, end) 자리를 이 주소로 연결한다.
 *
 * @param start 답 글 안 시작 위치(UTF-16 글자 단위, 자바스크립트 문자열 위치와 같다)
 * @param end   끝 위치(이 자리는 포함하지 않는다)
 * @param url   링크 주소
 */
public record AnswerLink(int start, int end, String url) {
}
