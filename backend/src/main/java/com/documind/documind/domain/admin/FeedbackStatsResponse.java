package com.documind.documind.domain.admin;

import lombok.Builder;
import lombok.Getter;

/**
 * 관리자 대시보드에서 표시할 답변 피드백 집계 응답 DTO.
 */
@Getter
@Builder
public class FeedbackStatsResponse {

    // 저장된 전체 피드백 수
    private long totalCount;

    // 좋아요 피드백 수
    private long positiveCount;

    // 싫어요 피드백 수
    private long negativeCount;

    // 좋아요 비율. 전체 피드백이 없으면 0.0
    private double positiveRate;
}
