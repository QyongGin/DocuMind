package com.documind.documind.domain.document;

import java.util.List;

/**
 * 게시 정보 채우기 결과.
 *
 * @param updated          게시 정보를 바꾼 문서 수(같은 대장 ID의 살아 있는 문서가 여럿이면 모두 센다)
 * @param missingLedgerIds 살아 있는 문서가 없는 대장 ID(지웠거나 아직 올리지 않은 문서)
 */
public record DocumentOriginUpdateResponse(int updated, List<String> missingLedgerIds) {
}
