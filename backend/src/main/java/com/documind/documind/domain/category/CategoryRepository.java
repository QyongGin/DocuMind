package com.documind.documind.domain.category;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

// JpaRepository<엔티티, PK타입>를 상속받으면 기본 CRUD 메서드가 자동 생성됨
public interface CategoryRepository extends JpaRepository<Category, Long> {

    /**
     * 카테고리 이름 중복 여부를 확인한다.
     *
     * @param name 확인할 이름
     * @return 동일한 이름의 카테고리가 존재하면 true
     */
    boolean existsByName(String name);

    /**
     * 전체 카테고리를 이름 오름차순으로 조회한다.
     *
     * @return 카테고리 목록 (이름 오름차순)
     */
    List<Category> findAllByOrderByNameAsc();
}
