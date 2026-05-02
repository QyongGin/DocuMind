package com.documind.documind.global.common;

import lombok.Getter;

// 모든 API 응답을 감싸는 공통 응답 형식. 프론트엔드가 success 필드로 성공/실패를 판단
// @Getter: 모든 필드의 getter 메서드 자동 생성 (Lombok)
@Getter
public class ApiResponse<T> {

    private final boolean success;
    private final T data;
    private final String message;

    private ApiResponse(boolean success, T data, String message) {
        this.success = success;
        this.data = data;
        this.message = message;
    }

    // 성공 응답 (data 포함)
    public static <T> ApiResponse<T> success(T data) {
        return new ApiResponse<>(true, data, null);
    }

    // 성공 응답 (data 없이 메시지만)
    public static <T> ApiResponse<T> success(String message) {
        return new ApiResponse<>(true, null, message);
    }

    // 실패 응답
    public static <T> ApiResponse<T> fail(String message) {
        return new ApiResponse<>(false, null, message);
    }
}
