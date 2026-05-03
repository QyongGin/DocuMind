package com.documind.documind.domain.category;

import com.documind.documind.global.common.ApiResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 카테고리 관련 엔드포인트를 처리하는 컨트롤러.
 * 생성은 ADMIN 전용, 목록 조회는 전체 허용 (SecurityConfig에서 제어).
 */
// @RestController: @Controller + @ResponseBody. JSON 응답을 자동으로 직렬화
@RestController
@RequestMapping("/api/categories")
@RequiredArgsConstructor
public class CategoryController {

    private final CategoryService categoryService;

    /**
     * POST /api/categories — 카테고리 생성 (ADMIN 전용).
     *
     * @param request 카테고리 이름 요청 DTO
     * @return 201 Created + 생성된 카테고리
     */
    @PostMapping
    public ResponseEntity<ApiResponse<CategoryResponse>> create(@Valid @RequestBody CategoryCreateRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success(categoryService.create(request)));
    }

    /**
     * GET /api/categories — 카테고리 목록 조회 (전체 허용).
     * 문서 업로드 폼의 카테고리 드롭다운 등에서 사용한다.
     *
     * @return 카테고리 목록 (이름 오름차순)
     */
    @GetMapping
    public ResponseEntity<ApiResponse<List<CategoryResponse>>> list() {
        return ResponseEntity.ok(ApiResponse.success(categoryService.list()));
    }
}
