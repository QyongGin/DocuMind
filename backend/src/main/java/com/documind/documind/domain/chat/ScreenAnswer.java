package com.documind.documind.domain.chat;

import java.util.List;

/**
 * 사용자 화면에 보이는 답(ADR-0050). 모델 원문에서 출처 번호를 지운 글, 답이 쓴 근거로 만든 참고한 문서,
 * 거절 문장만 있는 답에 붙이는 안내로 이루어진다.
 *
 * @param text          화면에 보이는 답 글(출처 번호를 지우고 꺾쇠 친 링크를 푼 것)
 * @param references    참고한 문서. 거절 문장만 있는 답이면 비어 있다
 * @param guidance      거절 문장만 있는 답에 붙이는 안내. 그 밖에는 null
 * @param citedSources  모델 원문이 쓴 출처 번호(나온 순서, 겹치지 않게). 개발자 모드의 화면 처리 내역에 쓴다
 * @param links         답 글 속 링크(나온 순서)
 */
public record ScreenAnswer(String text, List<ReferenceDocument> references, RefusalGuidance guidance,
                           List<Integer> citedSources, List<AnswerLink> links) {

    /**
     * 거절 문장만 나간 답인지(정해 둔 안내를 붙인 답). 관리자 '못 답한 질문'에 모은다(ADR-0052 결정 5).
     *
     * @return 거절 문장만 있는 답이면 true
     */
    public boolean refusedOnly() {
        return guidance != null;
    }
}
