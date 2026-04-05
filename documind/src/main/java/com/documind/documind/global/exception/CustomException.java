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
}
