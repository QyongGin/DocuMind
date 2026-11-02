package com.documind.documind.domain.document;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;

/**
 * 이미 올린 문서의 게시 정보 한 건(대장 ID로 문서를 찾는다). 관리자 API와 업로드 도구의 채우기 명령이 쓴다.
 *
 * @param ledgerId    문서 대장 ID(필수)
 * @param site        사이트 코드
 * @param siteName    사람이 읽는 사이트 이름
 * @param board       게시판 이름
 * @param title       문서 제목
 * @param parentTitle 첨부 파일이면 그 게시글 제목
 * @param parentUrl   첨부 파일이면 그 게시글 주소
 */
public record DocumentOriginUpdateRequest(String ledgerId, String site, String siteName, String board, String title,
                                          String parentTitle, String parentUrl) {

    /**
     * 형식을 검사한 대장 ID를 돌려준다.
     *
     * @return 앞뒤 공백을 뺀 대장 ID
     * @throws CustomException 대장 ID가 없거나 형식이 틀리면 INVALID_DOCUMENT_SOURCE
     */
    public String requiredLedgerId() {
        String checked = new DocumentSource(ledgerId, null, null, null).ledgerId();
        if (checked == null) {
            throw new CustomException(ErrorCode.INVALID_DOCUMENT_SOURCE, "게시 정보마다 대장 ID가 있어야 합니다.");
        }
        return checked;
    }

    /**
     * 검사를 통과한 게시 정보로 바꾼다.
     *
     * @return 게시 정보
     * @throws CustomException 형식이 틀리면 INVALID_DOCUMENT_SOURCE
     */
    public DocumentOrigin toOrigin() {
        return new DocumentOrigin(site, siteName, board, title, parentTitle, parentUrl);
    }
}
