package com.documind.documind.domain.document;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;

import java.util.regex.Pattern;

/**
 * 문서가 게시된 곳(사이트·게시판·제목)과 첨부 파일이면 그 게시글이다. 모든 칸은 선택이다.
 *
 * <p>답 화면의 '참고한 문서'를 만드는 데 쓴다(ADR-0050 결정 2, ADR-0051 결정 2). 값은 문서 대장 그대로 받고,
 * 화면 문구('학교 홈페이지', '학사 공지' 등)로 바꾸는 일은 답 변환이 한다. 빈 문자열은 null로 본다.</p>
 *
 * @param site        사이트 코드(예: www, ipsi, cs)
 * @param siteName    사람이 읽는 사이트 이름(예: 학교, 입학, AI소프트웨어학과)
 * @param board       게시판 이름(예: 학사(11)). 게시판 글이 아니면 null
 * @param title       문서 제목(게시글 제목, 페이지 제목, 첨부 파일 이름)
 * @param parentTitle 첨부 파일이면 그 게시글 제목
 * @param parentUrl   첨부 파일이면 그 게시글 주소(http·https)
 */
public record DocumentOrigin(String site, String siteName, String board, String title,
                             String parentTitle, String parentUrl) {

    /** 게시 정보가 없는 문서. */
    public static final DocumentOrigin EMPTY = new DocumentOrigin(null, null, null, null, null, null);

    private static final Pattern SITE = Pattern.compile("[A-Za-z0-9_-]{1,50}");
    private static final int MAX_NAME_LENGTH = 100;
    private static final int MAX_TITLE_LENGTH = 500;

    /**
     * 값을 정리하고 검사한다.
     *
     * @throws CustomException 형식이 틀리면 INVALID_DOCUMENT_SOURCE(어느 칸이 틀렸는지 메시지에 적음)
     */
    public DocumentOrigin {
        site = blankToNull(site);
        siteName = blankToNull(siteName);
        board = blankToNull(board);
        title = blankToNull(title);
        parentTitle = blankToNull(parentTitle);
        parentUrl = blankToNull(parentUrl);
        if (site != null && !SITE.matcher(site).matches()) {
            throw invalid("사이트 코드는 영문·숫자와 _ - 로 된 50자 이내여야 합니다.");
        }
        requireLength(siteName, MAX_NAME_LENGTH, "사이트 이름");
        requireLength(board, MAX_NAME_LENGTH, "게시판 이름");
        requireLength(title, MAX_TITLE_LENGTH, "제목");
        requireLength(parentTitle, MAX_TITLE_LENGTH, "게시글 제목");
        if (parentUrl != null && !DocumentSource.isHttpUrl(parentUrl)) {
            throw invalid("게시글 주소는 http 또는 https로 시작하는 1,000자 이내 주소여야 합니다.");
        }
    }

    // field는 받침 있는 낱말(이름, 제목)이라 조사는 '은'으로 붙인다
    private static void requireLength(String value, int max, String field) {
        if (value != null && value.length() > max) {
            throw invalid(field + "은 " + max + "자 이내여야 합니다.");
        }
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    private static CustomException invalid(String message) {
        return new CustomException(ErrorCode.INVALID_DOCUMENT_SOURCE, message);
    }
}
