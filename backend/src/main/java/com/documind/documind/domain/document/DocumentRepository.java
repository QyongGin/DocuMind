package com.documind.documind.domain.document;

import org.springframework.data.jpa.repository.JpaRepository;

// JpaRepository<엔티티, PK타입>를 상속받으면 기본 CRUD 메서드가 자동 생성됨
public interface DocumentRepository extends JpaRepository<Document, Long> {
}
