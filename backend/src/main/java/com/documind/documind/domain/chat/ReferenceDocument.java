package com.documind.documind.domain.chat;

import java.util.ArrayList;
import java.util.List;

/**
 * 참고한 문서 한 건(docs/project/챗봇-답변-형식.md §3 '참고한 문서 만드는 법').
 *
 * @param site            사이트 이름(예: 학교 홈페이지, AI소프트웨어학과 홈페이지). 모르면 null
 * @param board           게시판 이름(예: 학사 공지, 학사규정). 게시판 글이 아니면 null
 * @param title           게시글 제목. 첨부 파일은 그 게시글 제목(게시글이 대장에 없으면 첨부 파일 이름)
 * @param url             원문 보기 주소. 첨부 파일은 그 게시글 주소
 * @param attachmentNames 게시글로 연결한 첨부 파일 이름들
 * @param postedAt        게시일(YYYY-MM-DD). 모르면 null
 */
public record ReferenceDocument(String site, String board, String title, String url, List<String> attachmentNames,
                                String postedAt) {

    /**
     * 같은 게시글로 연결되는 다른 참고한 문서의 첨부 파일 이름을 더한다.
     *
     * @param other 같은 제목·주소의 참고한 문서
     * @return 첨부 파일 이름을 겹치지 않게 합친 참고한 문서
     */
    public ReferenceDocument withAttachmentsOf(ReferenceDocument other) {
        List<String> names = new ArrayList<>(attachmentNames);
        other.attachmentNames().stream().filter(name -> !names.contains(name)).forEach(names::add);
        return new ReferenceDocument(site, board, title, url, List.copyOf(names), postedAt);
    }
}
