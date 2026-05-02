package com.documind.documind.global.exception;

import com.documind.documind.global.common.ApiResponse;
import jakarta.validation.ConstraintViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.client.RestClientException;

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

    // FastAPI 호출 실패(연결 오류, 타임아웃, 4xx/5xx 등) 시 FASTAPI_UPLOAD_FAILED로 래핑
    @ExceptionHandler(RestClientException.class)
    public ResponseEntity<ApiResponse<Void>> handleRestClientException(RestClientException e) {
        ErrorCode errorCode = ErrorCode.FASTAPI_UPLOAD_FAILED;
        return ResponseEntity
                .status(errorCode.getHttpStatus())
                .body(ApiResponse.fail(errorCode.getMessage()));
    }

    // @Validated + @Min/@Max 등 @RequestParam 제약 위반 시 400 응답
    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ApiResponse<Void>> handleConstraintViolation(ConstraintViolationException e) {
        String message = e.getConstraintViolations().stream()
                .map(cv -> cv.getMessage())
                .findFirst()
                .orElse("입력값이 유효하지 않습니다.");
        return ResponseEntity
                .status(HttpStatus.BAD_REQUEST)
                .body(ApiResponse.fail(message));
    }

    // @Valid @RequestBody 검증 실패 시 400 응답. ConstraintViolationException과 포맷 통일
    @ExceptionHandler(org.springframework.web.bind.MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<Void>> handleMethodArgumentNotValid(
            org.springframework.web.bind.MethodArgumentNotValidException e) {
        String message = e.getBindingResult().getFieldErrors().stream()
                .map(fe -> fe.getDefaultMessage())
                .findFirst()
                .orElse("입력값이 유효하지 않습니다.");
        return ResponseEntity
                .status(HttpStatus.BAD_REQUEST)
                .body(ApiResponse.fail(message));
    }
}
