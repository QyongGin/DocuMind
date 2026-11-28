package com.documind.documind.domain.chat;

import com.documind.documind.domain.document.Document;
import com.documind.documind.domain.document.DocumentOrigin;
import com.documind.documind.domain.document.DocumentRepository;
import com.documind.documind.domain.document.DocumentSource;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 화면용 답 변환 단위 테스트(ADR-0050·0051). 경우별 모양은 docs/project/챗봇-답변-형식.md §2와 같다. 예시는 지어낸 가나대학이다.
 */
class ScreenAnswerMakerTest {

    private static final String REFUSAL = "학교 홈페이지 안내에서 찾지 못했습니다.";
    private static final RefusalGuidance GUIDANCE = new RefusalGuidance(
            "학과, 학년도, 학기를 넣어 다시 질문하기", "교내 전화번호 안내", "https://www.ganada.ac.kr/phone");

    private final DocumentRepository documentRepository = mock(DocumentRepository.class);
    private final ScreenAnswerMaker maker = new ScreenAnswerMaker(documentRepository, REFUSAL,
            GUIDANCE.retryHint(), GUIDANCE.contactLabel(), GUIDANCE.contactUrl());

    @Test
    @DisplayName("답이 있을 때: 출처 번호를 지우고 그 근거로 참고한 문서를 만든다")
    void answered() {
        Document notice = document(1L, "https://www.ganada.ac.kr/bbs/11/1", LocalDate.of(2026, 8, 10),
                new DocumentOrigin("www", "학교", "학사(11)", "2026학년도 2학기 휴학 신청 안내", null, null));
        given(notice);

        ScreenAnswer screen = maker.make("""
                2026학년도 2학기 휴학 신청 기간은 2026. 8. 18.(화) ~ 8. 29.(토)입니다. 문의는 학사지원팀(02-000-0000)으로 하시면 됩니다.

                [출처 1]""", sources(1L));

        assertEquals("2026학년도 2학기 휴학 신청 기간은 2026. 8. 18.(화) ~ 8. 29.(토)입니다. 문의는 학사지원팀(02-000-0000)으로 하시면 됩니다.",
                screen.text());
        assertEquals(List.of(new ReferenceDocument("학교 홈페이지", "학사 공지", "2026학년도 2학기 휴학 신청 안내",
                "https://www.ganada.ac.kr/bbs/11/1", List.of(), "2026-08-10")), screen.references());
        assertNull(screen.guidance());
        assertEquals(List.of(1), screen.citedSources());
        assertFalse(screen.workingLinesRemoved());
    }

    @Test
    @DisplayName("일부만 없을 때와 답이 없고 문의처가 있을 때: 거절 문장이 들어 있어도 안내를 붙이지 않고 참고한 문서를 보인다")
    void partialAndRefusalWithContact() {
        given(document(2L, "https://www.ganada.ac.kr/bbs/18/2", null,
                new DocumentOrigin("www", "학교", "장학(17)", "가나장학금 신청 안내", null, null)));

        ScreenAnswer partial = maker.make("통학버스는 20분 앞당겨 운행됩니다. 버스 요금은 " + REFUSAL + "\n\n[출처 2]",
                sources(9L, 2L));
        ScreenAnswer contact = maker.make(REFUSAL + " 장학팀(02-000-0001)으로 문의하시기 바랍니다.\n\n[출처 2]",
                sources(9L, 2L));

        assertNull(partial.guidance());
        assertEquals("장학 공지", partial.references().get(0).board());
        assertNull(contact.guidance());
        assertEquals("가나장학금 신청 안내", contact.references().get(0).title());
    }

    @Test
    @DisplayName("답이 없을 때: 거절 문장만 있으면(출처 번호가 붙어도) 정해 둔 안내를 붙이고 참고한 문서는 보이지 않는다")
    void refusalOnly() {
        given(document(1L, "https://www.ganada.ac.kr/bbs/11/1", null, DocumentOrigin.EMPTY));

        for (String raw : List.of(REFUSAL, REFUSAL + "\n\n[출처 1]", "  " + REFUSAL + " [출처 1]\n")) {
            ScreenAnswer screen = maker.make(raw, sources(1L));
            assertEquals(REFUSAL, screen.text());
            assertEquals(GUIDANCE, screen.guidance());
            assertEquals(List.of(), screen.references());
        }
    }

    @Test
    @DisplayName("확인 줄로 시작하는 답 세 모양: 결론 줄머리 뒤의 글만 보이고, 확인 줄을 뗐다고 남긴다")
    void workingLinesRemovedForThreeShapes() {
        given(document(2L, "https://www.ganada.ac.kr/bbs/11/2", null,
                new DocumentOrigin("www", "학교", "학사(11)", "2026학년도 학과별 모집 정원", null, null)));

        ScreenAnswer rows = maker.make("""
                확인한 행:
                - 가나학과: 40명
                - 다라학과: 35명
                - 마바학과: 20명 (해당 없음)
                결론: 정원이 30명을 넘는 학과는 가나학과와 다라학과입니다.

                [출처 2]""", sources(9L, 2L));
        ScreenAnswer passage = maker.make("""
                근거 글: 휴학 중인 학생은 신청할 수 없다.
                결론: 휴학 중에는 신청할 수 없습니다.

                [출처 2]""", sources(9L, 2L));
        ScreenAnswer table = maker.make("""

                고른 표: 2026학년도 → [학사일정] 2026학년도 수강신청 일정 [출처 2]
                결론: 2026학년도 수강신청은 2월 10일부터입니다.""", sources(9L, 2L));

        assertEquals("정원이 30명을 넘는 학과는 가나학과와 다라학과입니다.", rows.text());
        assertEquals("휴학 중에는 신청할 수 없습니다.", passage.text());
        assertEquals("2026학년도 수강신청은 2월 10일부터입니다.", table.text());
        for (ScreenAnswer screen : List.of(rows, passage, table)) {
            assertTrue(screen.workingLinesRemoved());
            assertEquals("2026학년도 학과별 모집 정원", screen.references().get(0).title());
        }
        // '고른 표:' 줄에만 있던 출처 번호도 참고한 문서에 들어간다
        assertEquals(List.of(2), table.citedSources());
    }

    @Test
    @DisplayName("확인 줄로 시작했는데 결론 줄이 없거나 결론이 비었으면 원문(출처 번호만 지운 것)을 그대로 보인다")
    void workingLinesWithoutConclusionShowRaw() {
        ScreenAnswer noConclusion = maker.make("확인한 행:\n- 가나학과: 40명\n- 다라학과: 35명\n\n[출처 1]", sources());
        ScreenAnswer emptyConclusion = maker.make("근거 글: 휴학 중인 학생은 신청할 수 없다.\n결론: [출처 1]", sources());

        assertEquals("확인한 행:\n- 가나학과: 40명\n- 다라학과: 35명", noConclusion.text());
        assertEquals("근거 글: 휴학 중인 학생은 신청할 수 없다.\n결론:", emptyConclusion.text());
        assertFalse(noConclusion.workingLinesRemoved());
        assertFalse(emptyConclusion.workingLinesRemoved());
    }

    @Test
    @DisplayName("확인 줄 뒤의 결론이 거절 문장뿐이면 정해 둔 안내를 붙이고 참고한 문서를 보이지 않는다")
    void workingLinesWithRefusalConclusion() {
        given(document(1L, "https://www.ganada.ac.kr/bbs/11/1", null, DocumentOrigin.EMPTY));

        ScreenAnswer screen = maker.make("고른 표: 2025학년도 → [학사일정] 2025학년도 수강신청 일정 [출처 1]\n결론: "
                + REFUSAL, sources(1L));

        assertEquals(REFUSAL, screen.text());
        assertEquals(GUIDANCE, screen.guidance());
        assertEquals(List.of(), screen.references());
        assertTrue(screen.refusedOnly());
    }

    @Test
    @DisplayName("확인 줄 머리로 시작하지 않는 답은 '결론:'이 들어 있어도 지금과 같다")
    void answersWithoutWorkingHeaderUnchanged() {
        for (String raw : List.of(
                "결론: 휴학은 8월까지입니다.\n\n[출처 1]",
                "가나학과 정원은 40명입니다.\n결론: 다라학과보다 많습니다.",
                "확인 결과 가나학과 정원은 40명입니다.\n결론: 다라학과보다 많습니다.",
                "검토한 결과 근거 글: 없음\n결론: 확인 필요")) {
            ScreenAnswer screen = maker.make(raw, sources());
            assertEquals(raw.replace("\n\n[출처 1]", ""), screen.text());
            assertFalse(screen.workingLinesRemoved());
        }
    }

    @Test
    @DisplayName("첨부 파일은 게시글로 연결하고, 같은 게시글의 첨부 여럿은 한 번만 보이며 파일 이름을 합친다")
    void attachmentsLinkToTheirPost() {
        DocumentOrigin form = new DocumentOrigin("www", "학교", "정보목록(32)·학사규정", "수강신청서.hwp",
                "수강신청 안내", "https://www.ganada.ac.kr/bbs/32/7");
        DocumentOrigin guide = new DocumentOrigin("www", "학교", "정보목록(32)·학사규정", "수강 편람.pdf",
                "수강신청 안내", "https://www.ganada.ac.kr/bbs/32/7");
        given(document(1L, "https://www.ganada.ac.kr/bbs/32/7/download/1", null, form),
                document(2L, "https://www.ganada.ac.kr/bbs/32/7/download/2", null, guide));

        ScreenAnswer screen = maker.make("수강신청은 학사 시스템에서 합니다. [출처 1, 2]", sources(1L, 2L));

        assertEquals(List.of(new ReferenceDocument("학교 홈페이지", "학사규정", "수강신청 안내",
                "https://www.ganada.ac.kr/bbs/32/7", List.of("수강신청서.hwp", "수강 편람.pdf"), null)), screen.references());
        assertEquals("수강신청은 학사 시스템에서 합니다.", screen.text());
    }

    @Test
    @DisplayName("꺾쇠 친 링크를 풀고, 범위 밖 출처 번호와 지운 문서는 참고한 문서에서 뺀다")
    void linksAndInvalidCitations() {
        Document deleted = document(1L, "https://www.ganada.ac.kr/bbs/11/1", null, DocumentOrigin.EMPTY);
        ReflectionTestUtils.setField(deleted, "isActive", false);
        given(deleted);

        ScreenAnswer screen = maker.make("신청은 <https://forms.ganada.ac.kr/a>에서 합니다. [출처 1] [출처 9]", sources(1L));

        assertEquals("신청은 https://forms.ganada.ac.kr/a에서 합니다.", screen.text());
        assertEquals(List.of(), screen.references());
        assertEquals(List.of(1, 9), screen.citedSources());
    }

    @Test
    @DisplayName("게시판 이름: 번호를 빼고 '공지'를 붙이되, 이미 '공지'로 끝나거나 분류가 붙은 게시판은 그대로 쓴다")
    void boardLabels() {
        assertEquals("학사 공지", ScreenAnswerMaker.boardLabel("학사(11)"));
        assertEquals("입학 공지", ScreenAnswerMaker.boardLabel("입학 공지(9)"));
        assertEquals("학사규정", ScreenAnswerMaker.boardLabel("정보목록(32)·학사규정"));
        assertNull(ScreenAnswerMaker.boardLabel(null));
        assertEquals("가나소프트웨어학과 홈페이지", ScreenAnswerMaker.siteLabel("가나소프트웨어학과"));
    }

    @Test
    @DisplayName("답 속 링크: 끝은 한글·괄호 앞에서 끊고 끝의 문장부호는 빼며, 자리는 답 글과 맞는다")
    void answerLinks() {
        String raw = "신청은 https://www.ganada.ac.kr/form이며, 결과는 (https://www.ganada.ac.kr/result)에서 봅니다. "
                + "목록은 <https://www.ganada.ac.kr/list.do?bbs=11&page=2>를 보시고 자세한 안내는 https://www.ganada.ac.kr/bbs/11/1."
                + "\n\n[출처 1]";

        ScreenAnswer answer = maker.make(raw, sources());

        assertEquals(List.of("https://www.ganada.ac.kr/form", "https://www.ganada.ac.kr/result",
                        "https://www.ganada.ac.kr/list.do?bbs=11&page=2", "https://www.ganada.ac.kr/bbs/11/1"),
                answer.links().stream().map(AnswerLink::url).toList());
        // 화면은 답 글의 [start, end) 자리를 링크로 바꾼다
        answer.links().forEach(link -> assertEquals(link.url(), answer.text().substring(link.start(), link.end())));
        assertEquals(List.of(), ScreenAnswerMaker.findLinks("주소가 없는 답입니다. https:// 만 있습니다."));
    }

    private void given(Document... documents) {
        when(documentRepository.findAllById(any())).thenAnswer(invocation -> {
            Collection<?> ids = invocation.getArgument(0);
            return List.of(documents).stream().filter(document -> ids.contains(document.getId())).toList();
        });
    }

    private static Document document(Long id, String url, LocalDate postedAt, DocumentOrigin origin) {
        Document document = Document.create(null, null, "f-" + id, "원래이름-" + id + ".pdf", 10L, "application/pdf",
                new DocumentSource("www/" + id, url, postedAt, null), null);
        ReflectionTestUtils.setField(document, "id", id);
        document.applyOrigin(origin);
        return document;
    }

    // N번째 출처가 근거 블록 [출처 N]이다
    private static List<Map<String, Object>> sources(Long... documentIds) {
        return List.of(documentIds).stream().map(id -> Map.<String, Object>of("document_id", String.valueOf(id))).toList();
    }
}
