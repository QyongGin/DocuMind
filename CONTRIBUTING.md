# DocuMind Contributing Guide

DocuMind는 사내 문서를 외부로 보내지 않는 on-premise(내부 설치형) RAG(검색 증강 생성) 시스템이다. 이 문서는 공개 저장소에서 개발자와 리뷰어가 같은 기준으로 작업하기 위한 협업 규칙이다.

이 문서에는 공개해도 되는 개발 절차만 둔다. 개인 서버 주소, 실제 `.env` 값, 로컬 배포 alias(별칭), `memory-bank/` 진행 상황, 비공개 운영 메모는 넣지 않는다.

## 1. 프로젝트 구성

| 경로 | 역할 |
|---|---|
| `frontend/` | React 19 + Vite 기반 사용자 화면 |
| `backend/` | Spring Boot + Java 기반 REST API 서버 |
| `ai-server/` | FastAPI + Python 기반 문서 parsing(파싱), chunking(청킹), retrieval(검색), answer generation(답변 생성) 서버 |
| `docker-compose.yml` | 로컬 또는 서버 실행용 서비스 묶음 |
| `backend/AGENTS.md` | Backend 공개 리뷰 체크리스트 |
| `frontend/AGENTS.md` | Frontend 공개 리뷰 체크리스트 |
| `ai-server/AGENTS.md` | AI server 공개 리뷰 체크리스트 |

루트 `AGENTS.md`, `CLAUDE.md`, `memory-bank/`, `docs/`는 로컬 운영 자료로 취급한다. 공개 협업 규칙은 이 `CONTRIBUTING.md`와 모듈별 `AGENTS.md`에 둔다.

## 2. 작업 단위

- 하나의 issue(이슈) 또는 하나의 명확한 목표만 한 branch(브랜치)에 담는다.
- feature(기능 추가), fix(버그 수정), refactor(동작 유지 구조 개선), docs(문서), chore(잡무성 변경)를 한 PR에 과도하게 섞지 않는다.
- 관련 없는 대규모 리팩토링은 현재 작업에 끼워 넣지 않고 별도 issue로 분리한다.
- 기존 사용자 동작, API response contract(응답 계약), DB schema(스키마), RAG evidence(근거) 품질을 바꾸는 작업은 테스트 또는 수동 검증 기록을 남긴다.
- 큰 작업은 parent issue(상위 이슈) 또는 Epic(상위 관리 이슈)로 만들고, 실제 구현은 child issue(파생 이슈) 단위로 나눈다.
- child issue PR은 `Closes #child`, 필요하면 `Related #parent`를 함께 적는다.

## 3. 브랜치 전략

기본 개발 branch는 `develop`이다.

| branch | 역할 |
|---|---|
| `main` | 안정 릴리스 기준 |
| `develop` | 기능 PR이 먼저 모이는 통합 개발 기준 |
| `feat/#이슈번호-작업명` | 기능 추가 |
| `fix/#이슈번호-작업명` | 버그 수정 |
| `refactor/#이슈번호-작업명` | 구조 개선 |
| `docs/#이슈번호-작업명` | 공개 문서 변경 |
| `release/YYYY-MM-DD` | `develop`을 `main`으로 올리는 릴리스 준비 |

원칙:

- 일반 작업 branch는 최신 `develop`에서 만든다.
- 일반 PR target은 `develop`이다.
- `main`으로 직접 PR을 만들지 않는다. 예외는 release PR과 긴급 hotfix(긴급 수정)뿐이다.
- `develop`에 모인 작업을 충분히 검증한 뒤 release PR로 `main`에 병합한다.
- merge된 작업 branch는 원격과 로컬에서 정리한다.

## 4. 브랜치 이름

이슈가 있으면 아래 형식을 사용한다.

```text
feat/#12-review-schedule
fix/#18-login-token-refresh
refactor/#21-rag-retrieval-contract
docs/#24-api-guide
chore/#30-docker-env-example
release/2026-06-06
```

이슈가 없고 로컬에서 작은 문서 또는 정리 작업을 할 때는 의미가 드러나는 이름을 사용한다.

```text
docs/contributing-guide
chore/update-env-example
```

## 5. 커밋 메시지

커밋 메시지는 Conventional Commits(커밋 메시지 표준) 형식을 따른다.

```text
type(scope): 작업 내용 (#이슈번호)
```

예시:

```text
feat(chat): SSE 답변 중단 API 추가 (#12)
fix(auth): refresh token 만료 처리 수정 (#18)
refactor(rag): 검색 후보 정규화 로직 분리 (#21)
docs(api): 문서 업로드 API 설명 추가 (#24)
```

자주 사용하는 `type`은 다음과 같다.

| type | 의미 |
|---|---|
| `feat` | 사용자 기능 추가 |
| `fix` | 버그 수정 |
| `refactor` | 동작을 유지한 구조 개선 |
| `test` | 테스트 추가 또는 수정 |
| `docs` | 공개 문서 수정 |
| `chore` | 빌드, 설정, 의존성, 운영 보조 작업 |

## 6. PR 작성 기준

PR은 리뷰어가 위험 지점을 빠르게 찾을 수 있어야 한다. 기본 target branch는 `develop`이다. 아래 구조를 기본으로 사용한다.

```markdown
## 배경

왜 이 변경이 필요한지 적는다.

## 대상 브랜치

develop

## 변경 내용

- 무엇을 바꿨는가
- 어떤 동작을 유도하는가

## 리뷰 포인트

- 리뷰어가 집중해서 봐야 할 파일, 흐름, 위험을 적는다.

## 변경 파일

- `path/to/file`: 역할

## 확인한 내용

- 실행한 테스트 또는 수동 검증

## 이슈

Closes #이슈번호
```

이슈를 완전히 끝내면 `Closes #이슈번호`를 사용한다. 일부 범위만 처리했거나 후속 검증이 남으면 `Related #이슈번호`를 사용한다.

## 7. 공통 코드 작성 원칙

- 기존 코드 스타일과 파일 구조를 먼저 따른다.
- public class(공개 클래스)와 public method(공개 메서드)에는 Javadoc(`/** */`)을 작성한다.
- 주석은 "무엇을 하는지"보다 "왜 이 판단이 필요한지"를 설명할 때 우선 사용한다.
- 비밀값, 토큰, 실제 서버 주소, 개인 로컬 경로, 운영 계정 정보는 커밋하지 않는다.
- debug log(디버그 로그), 임시 script(스크립트), 실험 output(출력물)은 의도적으로 리뷰할 파일이 아니면 커밋하지 않는다.
- 같은 로직이 반복되면 작은 함수, 값 객체, command object(명령 객체), DTO(데이터 전달 객체)로 책임을 분리한다.
- null(값 없음), 빈 값, 권한 없음, 외부 서버 실패, 중복 요청 같은 edge case(경계 사례)를 함께 고려한다.

## 8. Backend 규칙

Backend는 Spring Boot와 Java를 사용한다.

- 패키지는 domain(도메인) 중심 구조를 유지한다. 관련 Controller, Service, Repository, Entity, DTO는 같은 기능 영역에 모은다.
- Controller에는 HTTP 요청/응답 변환 책임만 둔다. 비즈니스 판단은 Service 또는 domain object(도메인 객체)로 이동한다.
- 인증과 인가가 필요한 API는 Security 설정, Service 소유권 검증, 테스트를 함께 확인한다.
- JPA Entity(엔티티)는 무분별한 setter(설정 메서드)보다 생성자, 정적 팩토리, 의미 있는 변경 메서드를 우선 사용한다.
- DB 변경은 Flyway migration(마이그레이션) 또는 기존 schema(스키마) 전략과 충돌하지 않는지 확인한다.
- 예외는 공통 `ErrorCode`와 전역 예외 처리 흐름에 맞춘다.

Backend 변경 후 가능한 범위에서 아래 명령을 확인한다.

```bash
cd backend
./gradlew test
```

## 9. Frontend 규칙

Frontend는 React와 Vite를 사용한다.

- API 호출 세부 구현은 화면 component(컴포넌트)에 직접 흩뿌리지 않고 service(서비스) 계층에 모은다.
- 로그인, 로그아웃, token(토큰) 만료, 비로그인 session(세션), SSE(streaming, 스트리밍) 중단 상태가 서로 꼬이지 않게 관리한다.
- 삭제, 로그아웃, 문서 제거처럼 파괴적인 동작은 명확한 확인과 사용자 feedback(피드백)을 제공한다.
- 화면 텍스트는 모바일과 데스크톱에서 부모 영역을 넘치지 않아야 한다.
- modal(모달), drawer(드로어), popover(팝오버)는 focus(초점), Escape, 외부 클릭, `aria-*` 속성을 확인한다.

Frontend 변경 후 가능한 범위에서 아래 명령을 확인한다.

```bash
cd frontend
npm run lint
npm run build
```

## 10. AI Server와 RAG 규칙

AI server는 FastAPI와 Python을 사용한다. RAG 관련 변경은 특정 문서명, 특정 질문, 특정 페이지 번호에 맞춘 hard coding(하드코딩)으로 만들지 않는다.

- parser(파서), cleanup(정리), chunking(청킹), embedding(임베딩), retrieval(검색), reranking(재정렬), prompt construction(프롬프트 구성), answer generation(답변 생성)의 책임을 구분한다.
- ChromaDB metadata(메타데이터)에는 문서 ID, 원본 파일명, source(출처), page/span(페이지/범위)처럼 삭제와 출처 표시에 필요한 값을 유지한다.
- `table_fact`, `layout_parallel`, `query_evidence_facts` 같은 구조화 근거는 원문 raw text(원문 텍스트)와 역할을 섞지 않는다.
- `/debug/rag-trace`, `evaluate_rag.py`, `check_chunks.py` 결과로 검색 후보와 답변 근거를 확인한다.
- PDF, DOCX, PPTX, XLSX 중 한 형식만 좋아지고 다른 형식이 깨지는 format asymmetry(형식 비대칭)를 주의한다.
- 검색 결과가 없거나 근거가 부족할 때는 LLM이 추측하지 않도록 unsupported(근거 부족) 답변 흐름을 유지한다.

AI server 변경 후 가능한 범위에서 아래 명령을 확인한다.

```bash
cd ai-server
python3 -m py_compile main.py document_blocks.py layout_blocks.py layout_confidence.py check_chunks.py evaluate_rag.py compare_pdf_layout.py
python3 evaluate_rag.py --help
python3 check_chunks.py --help
```

## 11. Docker와 환경 변수

- 실제 `.env` 파일은 커밋하지 않는다.
- 새 환경 변수를 추가하면 `.env.example`에도 공개 가능한 예시 값을 추가한다.
- Docker Compose 설정 변경 후 가능한 범위에서 아래 명령으로 설정 문법을 확인한다.

```bash
docker compose -f docker-compose.yml --env-file .env.example config --quiet
```

## 12. 테스트와 검증 기준

작업 유형별 최소 확인 범위는 다음과 같다.

| 작업 유형 | 최소 확인 |
|---|---|
| Backend API | 단위/통합 테스트, 인증/인가 실패 케이스, 예외 응답 |
| Frontend UI | lint, build, 주요 사용자 흐름 수동 확인 |
| AI/RAG | `py_compile`, trace 확인, 평가 질문 또는 대표 질문 수동 확인 |
| DB schema | migration 적용 가능성, 기존 데이터 호환성 |
| Docker/infra | Compose config 검증, 환경 변수 예시 확인 |
| 문서만 변경 | 맞춤법, 공개 가능성, 링크/명령어 정확성, trailing whitespace(줄 끝 공백) 확인 |

모든 테스트를 항상 실행할 수는 없다. 실행하지 못한 테스트가 있으면 PR 본문에 이유와 남은 위험을 적는다.

## 13. 리뷰 전 자체 점검

PR을 올리기 전 아래 항목을 확인한다.

- 변경이 issue의 목적과 직접 연결되는가
- 관련 없는 파일이나 실험 output이 포함되지 않았는가
- 공개 저장소에 올리면 안 되는 정보가 없는가
- API request/response contract가 바뀌었다면 호출하는 쪽도 함께 수정했는가
- 인증/인가, 소유권 검증, 익명 사용자 흐름이 깨지지 않는가
- RAG 변경은 source citation(출처 인용), grounding(근거 고정), unsupported 답변 흐름을 해치지 않는가
- 테스트 또는 수동 검증으로 핵심 동작을 확인했는가
- 리뷰어가 집중해야 할 위험 지점을 PR 본문에 적었는가
