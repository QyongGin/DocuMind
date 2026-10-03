package com.documind.documind.global.exception;

import lombok.Getter;

// 서비스 계층에서 발생하는 비즈니스 예외. RuntimeException을 상속해 트랜잭션 롤백 대상이 됨
@Getter
public class CustomException extends RuntimeException {

    private final ErrorCode errorCode;

    public CustomException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
    }

    /**
     * ErrorCode의 상태코드를 쓰되, 사용자에게 보일 메시지를 상황에 맞게 바꾼다.
     *
     * @param errorCode 상태코드를 정하는 에러 코드
     * @param message   응답 메시지. 화면에 그대로 보여도 되는 문장만 넣는다
     */
    public CustomException(ErrorCode errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }
}
