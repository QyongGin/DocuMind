package com.documind.documind.domain.category;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

/**
 * 카테고리 생성·조회 비즈니스 로직을 담당한다.
 */
// @Service: 스프링 빈으로 등록. 비즈니스 로직 계층임을 명시
@Service
@RequiredArgsConstructor
public class CategoryService {

    private final CategoryRepository categoryRepository;

    /**
     * 카테고리를 생성한다. 이름 중복 시 CONFLICT 오류를 반환한다.
     *
     * @param request 카테고리 이름 요청 DTO
     * @return 생성된 카테고리 응답 DTO
     * @throws CustomException 동일한 이름이 이미 존재하는 경우 CATEGORY_ALREADY_EXISTS
     */
    @Transactional
    public CategoryResponse create(CategoryCreateRequest request) {
        if (categoryRepository.existsByName(request.getName())) {
            throw new CustomException(ErrorCode.CATEGORY_ALREADY_EXISTS);
        }
        // existsByName → save() 사이 동시 요청으로 unique 제약 위반 발생 시 명시적 예외로 변환한다.
        // ADMIN 전용이라 실제 발생 가능성은 낮지만 DB constraint 위반을 500으로 노출하지 않도록 보호한다.
        try {
            Category category = categoryRepository.save(Category.create(request.getName()));
            return CategoryResponse.from(category);
        } catch (DataIntegrityViolationException e) {
            throw new CustomException(ErrorCode.CATEGORY_ALREADY_EXISTS);
        }
    }

    /**
     * 전체 카테고리를 이름 오름차순으로 조회한다.
     * 문서 업로드 폼의 카테고리 선택 드롭다운 등 공개 API에서 사용한다.
     *
     * @return 카테고리 목록 (이름 오름차순)
     */
    @Transactional(readOnly = true)
    public List<CategoryResponse> list() {
        return categoryRepository.findAllByOrderByNameAsc()
                .stream()
                .map(CategoryResponse::from)
                .collect(Collectors.toList());
    }
}
