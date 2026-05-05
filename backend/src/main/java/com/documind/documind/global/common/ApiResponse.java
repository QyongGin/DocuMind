package com.documind.documind.global.common;

import lombok.Getter;

/**
 * 모든 API 응답을 감싸는 공통 응답 형식.
 * 프론트엔드가 success 필드로 성공/실패를 판단한다.
 */
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

    /** 성공 응답 — data 포함. String을 data로 반환할 때도 이 메서드를 사용한다. */
    public static <T> ApiResponse<T> success(T data) {
        return new ApiResponse<>(true, data, null);
    }

    /**
     * 성공 응답 — data 없이 사용자 안내 메시지만 반환.
     * 삭제·변경처럼 반환할 data가 없는 작업에 사용한다.
     * success(T data)와 String 인수 충돌을 막기 위해 메서드명을 구분한다.
     */
    public static <T> ApiResponse<T> successMessage(String message) {
        return new ApiResponse<>(true, null, message);
    }

    /** 실패 응답 — 오류 메시지 포함. */
    public static <T> ApiResponse<T> fail(String message) {
        return new ApiResponse<>(false, null, message);
    }
}
