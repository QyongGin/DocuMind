package com.documind.documind.domain.document;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.category.Category;
import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

// DB의 documents 테이블과 매핑되는 Entity 클래스임을 선언
@Entity
// 매핑할 테이블 이름 지정
@Table(name = "documents")
// 모든 필드의 getter 메서드 자동 생성 (Lombok)
@Getter
// 기본 생성자 자동 생성, PROTECTED로 설정해 외부에서 직접 new Document() 못하게 막음
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Document {

    // PK 지정
    @Id
    // AUTO_INCREMENT (DB가 값을 자동 증가시킴)
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // users 테이블과의 N:1 관계. LAZY: 실제 접근 시점에만 SELECT 쿼리 실행
    @ManyToOne(fetch = FetchType.LAZY)
    // FK 컬럼명 지정. nullable=false: 문서는 반드시 업로드한 사용자가 존재해야 함
    @JoinColumn(name = "uploaded_by", nullable = false)
    private User uploadedBy;

    // categories 테이블과의 N:1 관계. LAZY: 실제 접근 시점에만 SELECT 쿼리 실행
    @ManyToOne(fetch = FetchType.LAZY)
    // FK 컬럼명 지정. nullable=true: 카테고리 미분류 문서 허용
    @JoinColumn(name = "category_id", nullable = true)
    private Category category;

    // 서버 저장 파일명 (UUID 등으로 생성). NOT NULL, 최대 길이 255
    @Column(nullable = false, length = 255)
    private String fileName;

    // 업로드된 원본 파일명. NOT NULL, 최대 길이 255
    @Column(nullable = false, length = 255)
    private String originalName;

    // 파일 크기 (bytes 단위). NOT NULL
    @Column(nullable = false)
    private Long fileSize;

    // 파일 형식 (예: application/pdf). NOT NULL, 최대 길이 100
    @Column(nullable = false, length = 100)
    private String mimeType;

    // ChromaDB에 저장된 청크 수. 벡터 임베딩 완료 여부 확인에 사용. 기본값 0
    @Column(nullable = false)
    private Integer chunkCount = 0;

    // 논리삭제 플래그. 물리삭제 대신 is_active=false로 비활성화해 FK 무결성 보존
    @Column(nullable = false)
    private Boolean isActive = true;

    // 문서 자동 요약 결과. 고도화 단계에서 사용하므로 현재는 NULL 유지
    @Column(columnDefinition = "TEXT")
    private String summary;

    // NOT NULL, updatable=false: 최초 저장 후 변경 불가
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    // DB에 INSERT 되기 직전에 자동 실행되는 메서드
    @PrePersist
    protected void onCreate() {
        this.createdAt = LocalDateTime.now();
    }
}