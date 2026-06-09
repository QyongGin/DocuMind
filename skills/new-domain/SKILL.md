---
name: new-domain
description: DocuMind 새 도메인 추가 — Entity, Repository, Service, Controller, DTO 표준 구조 생성
origin: DocuMind
tags: [spring-boot, domain, java]
version: 1.0.0
---

# 새 도메인 추가 스킬

## 언제 사용하는가

새 비즈니스 도메인 폴더를 만들 때 (예: `category/`, `admin/`, `feedback/`).
이슈 시작 전 이 파일을 읽고 구조를 먼저 확인한다.

---

## 패키지 경로 규칙

```
documind/src/main/java/com/documind/documind/domain/{도메인명}/
```

모든 파일이 같은 폴더에 위치한다. 계층형(controller/service/repository 폴더 분리) 구조 절대 사용 금지.

---

## 필수 파일 5종

### 1. Entity — `{Name}.java`

```java
@Entity
@Table(name = "{테이블명}") // DB 테이블명
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class {Name} {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY) // PK 자동 증가
    private Long id;

    // 필드 선언
    @Column(nullable = false)
    private String name;

    @Column(name = "is_active", nullable = false)
    private boolean active = true; // 논리삭제 기본값

    @CreationTimestamp // 생성 시 자동 설정
    private LocalDateTime createdAt;

    // 정적 팩토리 메서드
    public static {Name} create(String name) {
        {Name} entity = new {Name}();
        entity.name = name;
        return entity;
    }
}
```

**체크리스트:**
- `@NoArgsConstructor(access = AccessLevel.PROTECTED)` — JPA 요구사항 + 외부 직접 생성 방지
- `is_active` 논리삭제 필드 — FK 무결성 보존 원칙
- 정적 팩토리 메서드로 생성

---

### 2. Repository — `{Name}Repository.java`

```java
public interface {Name}Repository extends JpaRepository<{Name}, Long> {
    // 기본 CRUD는 JpaRepository가 제공. 커스텀 쿼리만 추가
    List<{Name}> findAllByActiveTrue();
}
```

---

### 3. Service — `{Name}Service.java`

```java
@Service // 스프링 빈 등록
@RequiredArgsConstructor // final 필드 생성자 주입
public class {Name}Service {

    private final {Name}Repository {name}Repository;

    @Transactional(readOnly = true) // 조회는 readOnly
    public List<{Name}Response> findAll() {
        return {name}Repository.findAllByActiveTrue()
                .stream()
                .map({Name}Response::from)
                .toList();
    }

    @Transactional // 변경은 일반 트랜잭션
    public Long create({Name}Request request) {
        {Name} entity = {Name}.create(request.getName());
        return {name}Repository.save(entity).getId();
    }
}
```

---

### 4. Controller — `{Name}Controller.java`

```java
@RestController // REST API 컨트롤러
@RequiredArgsConstructor
@RequestMapping("/api/{도메인경로}")
public class {Name}Controller {

    private final {Name}Service {name}Service;

    @GetMapping
    public ResponseEntity<ApiResponse<List<{Name}Response>>> findAll() {
        return ResponseEntity.ok(ApiResponse.success({name}Service.findAll()));
    }

    @PostMapping
    public ResponseEntity<ApiResponse<Long>> create(@RequestBody @Valid {Name}Request request) {
        return ResponseEntity.ok(ApiResponse.success({name}Service.create(request)));
    }
}
```

---

### 5. DTO — `{Name}Request.java` / `{Name}Response.java`

```java
// Request DTO
@Getter
@NoArgsConstructor
public class {Name}Request {

    @NotBlank(message = "이름은 필수입니다") // 입력 검증
    private String name;
}

// Response DTO
@Getter
@AllArgsConstructor
public class {Name}Response {

    private Long id;
    private String name;

    public static {Name}Response from({Name} entity) {
        return new {Name}Response(entity.getId(), entity.getName());
    }
}
```

---

## Spring Security 접근 권한 설정

새 도메인을 추가하면 `SecurityConfig.java`에서 접근 권한을 명시해야 한다.

```java
// ADMIN 전용 엔드포인트 예시
.requestMatchers(HttpMethod.POST, "/api/{도메인경로}").hasRole("ADMIN")
.requestMatchers(HttpMethod.DELETE, "/api/{도메인경로}/**").hasRole("ADMIN")

// USER 접근 허용 (인증 불필요) 예시
.requestMatchers(HttpMethod.GET, "/api/{도메인경로}").permitAll()
```

---

## 어노테이션 주석 규칙

**처음 나오는 어노테이션에는 반드시 주석 작성.** 같은 파일 내 반복 사용은 생략.

| 어노테이션 | 설명 |
|---|---|
| `@Entity` | JPA 엔티티 — DB 테이블과 매핑 |
| `@Service` | 스프링 빈 등록 — 비즈니스 로직 계층 |
| `@RestController` | REST API 컨트롤러 — JSON 응답 자동 처리 |
| `@RequiredArgsConstructor` | final 필드 생성자 주입 자동 생성 |
| `@Transactional(readOnly = true)` | 읽기 전용 트랜잭션 — 성능 최적화 |

---

## 안티패턴 (하지 말 것)

- `@Autowired` 필드 주입 — 생성자 주입(`@RequiredArgsConstructor`) 사용
- `new` 키워드로 Entity 직접 생성 — 정적 팩토리 메서드 사용
- Service에 HTTP 관련 로직 — Controller에 위치
- Repository에 비즈니스 로직 — Service에 위치
- 물리삭제(`deleteById`) — 논리삭제(`is_active = false`)로 대체

---

## 관련 파일

- `global/common/ApiResponse.java` — 공통 응답 래퍼
- `global/exception/CustomException.java` — 예외 처리
- `global/config/SecurityConfig.java` — 접근 권한 설정
