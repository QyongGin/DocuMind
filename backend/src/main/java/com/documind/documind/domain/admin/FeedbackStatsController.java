package com.documind.documind.domain.admin;

import com.documind.documind.domain.chat.ChatFeedbackRepository;
import com.documind.documind.global.common.ApiResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 관리자 대시보드의 답변 피드백 집계 API.
 * 상세 추적은 고도화 범위로 두고, MVP에서는 전체 좋아요/싫어요 총량만 제공한다.
 */
@RestController
@RequestMapping("/api/admin/feedback-stats")
@RequiredArgsConstructor
public class FeedbackStatsController {

    private static final byte POSITIVE_SCORE = 1;
    private static final byte NEGATIVE_SCORE = -1;

    private final ChatFeedbackRepository chatFeedbackRepository;

    /**
     * GET /api/admin/feedback-stats — 전체 답변 피드백 집계를 조회한다.
     *
     * @return 전체, 좋아요, 싫어요, 좋아요 비율 지표
     */
    @GetMapping
    public ResponseEntity<ApiResponse<FeedbackStatsResponse>> stats() {
        long positiveCount = chatFeedbackRepository.countByScore(POSITIVE_SCORE);
        long negativeCount = chatFeedbackRepository.countByScore(NEGATIVE_SCORE);
        long totalCount = positiveCount + negativeCount;
        double positiveRate = totalCount == 0 ? 0.0 : (double) positiveCount / totalCount;

        FeedbackStatsResponse response = FeedbackStatsResponse.builder()
                .totalCount(totalCount)
                .positiveCount(positiveCount)
                .negativeCount(negativeCount)
                .positiveRate(positiveRate)
                .build();
        return ResponseEntity.ok(ApiResponse.success(response));
    }
}
