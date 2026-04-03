package com.documind.documind.domain.category;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

// DB의 categories 테이블과 매핑되는 Entity 클래스임을 선언
@Entity
// 매핑할 테이블 이름 지정
@Table(name = "categories")
// 모든 필드의 getter 메서드 자동 생성 (Lombok)
@Getter
// 기본 생성자 자동 생성, PROTECTED로 설정해 외부에서 직접 new Category() 못하게 막음
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Category {

    // PK 지정
    @Id
    // AUTO_INCREMENT (DB가 값을 자동 증가시킴)
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // 카테고리 이름. NOT NULL, UNIQUE, 최대 길이 100
    @Column(nullable = false, unique = true, length = 100)
    private String name;

    // NOT NULL, updatable=false: 최초 저장 후 변경 불가
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    // DB에 INSERT 되기 직전에 자동 실행되는 메서드
    @PrePersist
    protected void onCreate() {
        this.createdAt = LocalDateTime.now();
    }
}