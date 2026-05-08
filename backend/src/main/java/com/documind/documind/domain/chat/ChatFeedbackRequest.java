package com.documind.documind.domain.chat;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 답변 피드백 등록·수정 요청 DTO.
 * score는 1(좋아요) 또는 -1(싫어요)만 허용한다.
 */
@Getter
@NoArgsConstructor
public class ChatFeedbackRequest {

    // 피드백 점수. 1=좋아요, -1=싫어요. 0은 의미가 없으므로 서비스에서 거부한다.
    @NotNull(message = "피드백 점수는 필수입니다.")
    @Min(value = -1, message = "피드백 점수는 -1 또는 1이어야 합니다.")
    @Max(value = 1, message = "피드백 점수는 -1 또는 1이어야 합니다.")
    private Integer score;

    /**
     * 요청 점수를 DB 저장용 byte 값으로 변환한다.
     *
     * @return 1 또는 -1
     */
    public byte normalizedScore() {
        if (score == null || score == 0) {
            throw new CustomException(ErrorCode.INVALID_FEEDBACK_SCORE);
        }
        return score.byteValue();
    }
}
