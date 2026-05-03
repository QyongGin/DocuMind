package com.documind.documind.domain.document;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;
import java.util.Optional;

// JpaRepository<엔티티, PK타입>를 상속받으면 기본 CRUD 메서드가 자동 생성됨
public interface DocumentRepository extends JpaRepository<Document, Long> {

    /**
     * 활성화된 문서 전체를 생성일 내림차순으로 조회한다. 논리 삭제된 문서는 제외한다.
     *
     * <p>category는 LAZY 로딩이므로 파생 쿼리 사용 시 문서 N개에 대해 N번 추가 SELECT가 발생한다.
     * LEFT JOIN FETCH로 category를 한 번에 조회해 N+1을 방지한다.</p>
     *
     * @return is_active=true인 문서 목록 (최신순)
     */
    @Query("SELECT d FROM Document d LEFT JOIN FETCH d.category WHERE d.isActive = true ORDER BY d.createdAt DESC")
    List<Document> findAllByIsActiveTrueOrderByCreatedAtDesc();

    /**
     * 특정 ID의 활성화된 문서를 조회한다. 논리 삭제된 문서는 제외한다.
     *
     * @param id 문서 PK
     * @return is_active=true인 문서. 없으면 empty
     */
    Optional<Document> findByIdAndIsActiveTrue(Long id);
}
