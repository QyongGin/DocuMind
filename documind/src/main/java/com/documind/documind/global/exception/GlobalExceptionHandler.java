package com.documind.documind.global.exception;

import com.documind.documind.global.common.ApiResponse;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

// 컨트롤러에서 발생하는 예외를 전역으로 처리. @RestControllerAdvice: 모든 컨트롤러에 적용
@RestControllerAdvice
public class GlobalExceptionHandler {

    // CustomException 발생 시 ErrorCode에 정의된 상태코드와 메시지로 응답
    @ExceptionHandler(CustomException.class)
    public ResponseEntity<ApiResponse<Void>> handleCustomException(CustomException e) {
        ErrorCode errorCode = e.getErrorCode();
        return ResponseEntity
                .status(errorCode.getHttpStatus())
                .body(ApiResponse.fail(errorCode.getMessage()));
    }
}
