package com.documind.documind.domain.chat;

import com.documind.documind.domain.document.Document;
import com.documind.documind.domain.document.DocumentOrigin;
import com.documind.documind.domain.document.DocumentRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * 모델 원문 답을 사용자 화면의 답으로 바꾼다(ADR-0050·0051, docs/project/챗봇-답변-형식.md §3).
 *
 * <p>출처 번호({@code [출처 N]})를 지우고, 답이 쓴 근거(N번째 출처)의 문서 게시 정보로 참고한 문서를 만든다.
 * 거절 문장만 있는 답에는 정해 둔 안내를 붙이고 참고한 문서를 보이지 않는다. 같은 원문과 출처 목록이면 결과가
 * 같아서, 대화 기록을 다시 열 때도 저장한 원문으로 다시 만든다.</p>
 */
@Component
public class ScreenAnswerMaker {

    // 출처 번호와 그 앞의 공백·줄바꿈. 답 끝의 '\n\n[출처 1]', 문장 안의 ' [출처 2]', 묶어 쓴 '[출처 1, 3]'을 함께 지운다
    private static final Pattern CITATION = Pattern.compile("\\s*\\[출처\\s*(\\d+(?:\\s*[,·]\\s*\\d+)*)\\]");
    private static final Pattern NUMBER = Pattern.compile("\\d+");
    private static final Pattern ANGLE_LINK = Pattern.compile("<(https?://[^\\s<>]+)>");
    private static final Pattern BOARD_NUMBER = Pattern.compile("\\(\\d+\\)$");
    // 대장의 게시판 이름은 '게시판(번호)' 또는 분류가 붙은 '게시판(번호)·분류'(예: 정보목록(32)·학사규정) 꼴이다
    private static final String BOARD_CATEGORY_SEPARATOR = "·";
    private static final String NOTICE = "공지";
    private static final String HOMEPAGE = " 홈페이지";

    private final DocumentRepository documentRepository;
    private final String refusalSentence;
    private final RefusalGuidance refusalGuidance;

    /**
     * @param documentRepository 참고한 문서의 게시 정보를 읽는다
     * @param refusalSentence    모델이 학습으로 쓰는 거절 문장(AI 서버 운영 규칙 9·11과 같아야 한다)
     * @param retryHint          정해 둔 안내: 다시 묻는 방법
     * @param contactLabel       정해 둔 안내: 문의처 안내 이름
     * @param contactUrl         정해 둔 안내: 문의처 안내 주소
     */
    public ScreenAnswerMaker(DocumentRepository documentRepository,
                             @Value("${chat.answer.refusal-sentence}") String refusalSentence,
                             @Value("${chat.answer.retry-hint}") String retryHint,
                             @Value("${chat.answer.contact-label}") String contactLabel,
                             @Value("${chat.answer.contact-url}") String contactUrl) {
        this.documentRepository = documentRepository;
        this.refusalSentence = refusalSentence.strip();
        this.refusalGuidance = new RefusalGuidance(retryHint, contactLabel, contactUrl);
    }

    /**
     * 모델 원문 답과 출처 목록(근거 블록 순서)으로 화면용 답을 만든다.
     *
     * @param rawAnswer 모델 원문 답. null이면 빈 답
     * @param sources   AI 서버가 돌려준 출처 목록. N번째가 근거 블록 [출처 N]이다
     * @return 화면용 답
     */
    public ScreenAnswer make(String rawAnswer, List<Map<String, Object>> sources) {
        String raw = rawAnswer == null ? "" : rawAnswer;
        List<Integer> cited = new ArrayList<>();
        Matcher matcher = CITATION.matcher(raw);
        while (matcher.find()) {
            Matcher numbers = NUMBER.matcher(matcher.group(1));
            while (numbers.find()) {
                int number = Integer.parseInt(numbers.group());
                if (!cited.contains(number)) {
                    cited.add(number);
                }
            }
        }
        String text = tidy(ANGLE_LINK.matcher(CITATION.matcher(raw).replaceAll("")).replaceAll("$1"));
        if (text.equals(refusalSentence)) {
            return new ScreenAnswer(text, List.of(), refusalGuidance, List.copyOf(cited));
        }
        return new ScreenAnswer(text, references(cited, sources), null, List.copyOf(cited));
    }

    private List<ReferenceDocument> references(List<Integer> cited, List<Map<String, Object>> sources) {
        if (cited.isEmpty() || sources == null || sources.isEmpty()) {
            return List.of();
        }
        List<Long> documentIds = new ArrayList<>();
        for (int number : cited) {
            if (number >= 1 && number <= sources.size()) {
                documentId(sources.get(number - 1)).filter(id -> !documentIds.contains(id)).ifPresent(documentIds::add);
            }
        }
        Map<Long, Document> documents = documentRepository.findAllById(documentIds).stream()
                .filter(document -> Boolean.TRUE.equals(document.getIsActive()))
                .collect(Collectors.toMap(Document::getId, document -> document));
        // 같은 게시글로 연결되는 문서(같은 글의 첨부 여럿)는 한 번만 보이고 첨부 파일 이름을 합친다
        Map<String, ReferenceDocument> byLink = new LinkedHashMap<>();
        for (Long id : documentIds) {
            Document document = documents.get(id);
            if (document != null) {
                ReferenceDocument reference = toReference(document);
                byLink.merge(reference.title() + "\n" + reference.url(), reference, ReferenceDocument::withAttachmentsOf);
            }
        }
        return List.copyOf(byLink.values());
    }

    private static ReferenceDocument toReference(Document document) {
        DocumentOrigin origin = document.getOrigin();
        boolean underPost = origin.parentTitle() != null;
        String title = underPost ? origin.parentTitle()
                : origin.title() != null ? origin.title() : document.getOriginalName();
        String url = underPost ? origin.parentUrl() : document.getSourceUrl();
        List<String> attachments = underPost && origin.title() != null ? List.of(origin.title()) : List.of();
        String postedAt = document.getSourcePostedAt() == null ? null : document.getSourcePostedAt().toString();
        return new ReferenceDocument(siteLabel(origin.siteName()), boardLabel(origin.board()), title, url, attachments,
                postedAt);
    }

    static String siteLabel(String siteName) {
        return siteName == null ? null : siteName + HOMEPAGE;
    }

    /**
     * 대장의 게시판 이름을 화면 문구로 바꾼다: '학사(11)' → '학사 공지', '입학 공지(9)' → '입학 공지',
     * 분류가 붙은 '정보목록(32)·학사규정' → '학사규정'.
     */
    static String boardLabel(String board) {
        if (board == null) {
            return null;
        }
        int separator = board.lastIndexOf(BOARD_CATEGORY_SEPARATOR);
        if (separator >= 0) {
            return board.substring(separator + 1).strip();
        }
        String name = BOARD_NUMBER.matcher(board.strip()).replaceAll("").strip();
        return name.endsWith(NOTICE) ? name : name + " " + NOTICE;
    }

    private static Optional<Long> documentId(Map<String, Object> source) {
        Object value = source == null ? null : source.get("document_id");
        if (value == null) {
            return Optional.empty();
        }
        try {
            return Optional.of(Long.parseLong(String.valueOf(value)));
        } catch (NumberFormatException e) {
            return Optional.empty();
        }
    }

    // 지운 출처 번호가 남긴 빈칸과 빈 줄을 정리한다
    private static String tidy(String text) {
        return text.replaceAll("[ \\t]+\\n", "\n").replaceAll("\\n{3,}", "\n\n").strip();
    }
}
