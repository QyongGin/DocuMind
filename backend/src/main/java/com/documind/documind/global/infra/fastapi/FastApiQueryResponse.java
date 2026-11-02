package com.documind.documind.global.infra.fastapi;

import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

// FastAPI POST /query 응답을 역직렬화하는 DTO
// FastAPI 응답 형식: {"answer": "...", "sources": [{"document_id": "...", "source": "...", "content": "...", ...}], "trace": {...}}
@Getter
@NoArgsConstructor
public class FastApiQueryResponse {

    // LLM이 생성한 답변 텍스트
    private String answer;

    // 답변 근거 청크 목록. 헤더 메타데이터 키(Header 1 등)가 동적이므로 Map으로 수신
    private List<Map<String, Object>> sources;

    // 처리 기록(ADR-0052): 프롬프트, 단계별 걸린 초, 근거 후보별 검색 점수, 모델 설정. 옛 AI 서버는 보내지 않는다(null)
    private Map<String, Object> trace;
}
