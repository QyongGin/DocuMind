package com.documind.documind.domain.document;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;

import java.net.URI;
import java.net.URISyntaxException;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.regex.Pattern;

/**
 * 문서 대장에서 온 출처 정보(대장 ID·원래 주소·게시일·학년도)다. 모든 칸은 선택이다.
 *
 * <p>대량 업로드 명령은 대장 값을, 관리자 화면은 '추가 정보(선택)' 입력을 넣는다. 빈 문자열은 null로 본다.
 * 값은 서비스 DB 칸과 AI 서버 청크 메타데이터에 같은 이름으로 들어간다(#126 결정 1).</p>
 *
 * @param ledgerId     문서 대장 ID(예: www/bbs/11/110588/a162900)
 * @param url          원래 주소(http·https)
 * @param postedAt     원래 게시일
 * @param academicYear 학년도
 */
public record DocumentSource(String ledgerId, String url, LocalDate postedAt, Integer academicYear) {

    /** 출처 정보가 없는 업로드. */
    public static final DocumentSource EMPTY = new DocumentSource(null, null, null, null);

    private static final Pattern LEDGER_ID = Pattern.compile("[A-Za-z0-9._/-]{1,200}");
    private static final int MAX_URL_LENGTH = 1000;
    private static final int MIN_YEAR = 1990;
    private static final int MAX_YEAR = 2100;

    /**
     * 값을 정리하고 검사한다.
     *
     * @throws CustomException 형식이 틀리면 INVALID_DOCUMENT_SOURCE(어느 칸이 틀렸는지 메시지에 적음)
     */
    public DocumentSource {
        ledgerId = blankToNull(ledgerId);
        url = blankToNull(url);
        if (ledgerId != null && !LEDGER_ID.matcher(ledgerId).matches()) {
            throw invalid("대장 ID는 영문·숫자와 / . _ - 로 된 200자 이내여야 합니다.");
        }
        if (url != null && !isHttpUrl(url)) {
            throw invalid("원래 주소는 http 또는 https로 시작하는 1,000자 이내 주소여야 합니다.");
        }
        if (academicYear != null && (academicYear < MIN_YEAR || academicYear > MAX_YEAR)) {
            throw invalid("학년도는 " + MIN_YEAR + "~" + MAX_YEAR + " 사이여야 합니다.");
        }
    }

    /**
     * 요청 문자열에서 출처 정보를 만든다.
     *
     * @param ledgerId     대장 ID
     * @param url          원래 주소
     * @param postedAt     게시일(YYYY-MM-DD)
     * @param academicYear 학년도
     * @return 검사를 통과한 출처 정보
     * @throws CustomException 게시일 형식이 틀리면 INVALID_DOCUMENT_SOURCE
     */
    public static DocumentSource of(String ledgerId, String url, String postedAt, Integer academicYear) {
        String date = blankToNull(postedAt);
        LocalDate parsed;
        try {
            parsed = date == null ? null : LocalDate.parse(date);
        } catch (DateTimeParseException e) {
            throw invalid("게시일은 YYYY-MM-DD 형식이어야 합니다.");
        }
        return new DocumentSource(ledgerId, url, parsed, academicYear);
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    private static boolean isHttpUrl(String value) {
        if (value.length() > MAX_URL_LENGTH) {
            return false;
        }
        try {
            URI uri = new URI(value);
            String scheme = uri.getScheme();
            return ("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme)) && uri.getHost() != null;
        } catch (URISyntaxException e) {
            return false;
        }
    }

    private static CustomException invalid(String message) {
        return new CustomException(ErrorCode.INVALID_DOCUMENT_SOURCE, message);
    }
}
