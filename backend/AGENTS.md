# Backend Review Guide

> 이 파일은 GitHub PR에서 `@codex review`가 backend 변경을 검토할 때 참고하도록 저장소에 커밋된 공개 리뷰 체크리스트다.
> 비밀값, 로컬 운영 정보, 현재 진행률은 넣지 않는다. 실제 Spring Boot 구조와 맞지 않는 항목은 잘못된 리뷰를 유도하므로 바로 수정하거나 제거한다.

## Review guidelines

- 리뷰 코멘트는 한국어로 작성한다.
- 실제 버그, 인증/인가 문제, 데이터 유실 가능성, 테스트 누락, 운영 장애 위험을 우선 지적한다.
- 단순 스타일 취향이나 nit는 실제 결함 가능성이 있을 때만 지적한다.
- Controller에 비즈니스 로직이 직접 들어가지 않았는지 확인한다.
- Service 계층의 트랜잭션 경계와 소유권 검증이 적절한지 확인한다.
- 로그인 사용자와 비로그인 사용자의 분기가 `userId`와 `sessionKey` 기준으로 일관되게 동작하는지 확인한다.
- 인증이 필요한 API에 권한 검사가 누락되지 않았는지 확인한다.
- JWT, Refresh Token, 세션 키 처리에서 만료 토큰, 익명 요청, 재발급 실패 흐름이 안전한지 확인한다.
- JPA 사용 시 N+1 쿼리, 불필요한 DB 조회, 영속성 컨텍스트 오용 가능성이 있는지 확인한다.
- 예외 응답이 프로젝트의 공통 응답 형식과 `ErrorCode` 정책을 따르는지 확인한다.
- DB 스키마 변경은 기존 데이터와 호환되는지 확인한다.
- 핵심 비즈니스 로직 변경에는 성공 케이스뿐 아니라 권한 실패, 소유권 불일치, null/빈 값, 동시 요청 테스트가 있는지 확인한다.
- public 클래스와 public 메서드에는 프로젝트 규칙에 맞는 Javadoc이 있는지 확인한다.

## Clean code checklist

- 한 메서드는 한 가지 책임만 갖는지 확인한다.
- 메서드 인자가 4개 이상이면 command record, DTO, 값 객체로 묶을 수 있는지 검토한다.
- 불필요한 `else`와 깊은 indent를 피했는지 확인한다.
- 원시값이나 문자열이 반복적으로 정책 의미를 가지면 상수, 값 객체, record로 분리할 수 있는지 검토한다.
- 같은 조건문이나 문자열 가공 로직이 중복되면 작은 private helper로 추출할 수 있는지 검토한다.
- DTO와 Entity의 역할이 섞이지 않았는지 확인한다.

## Project-specific focus

- `domain/chat` 변경은 일반 질의응답과 SSE 스트리밍 저장 흐름을 함께 확인한다.
- `domain/auth` 변경은 Access Token, Refresh Token HttpOnly Cookie, logout/reissue 흐름을 함께 확인한다.
- `domain/document` 변경은 MySQL 문서 상태와 FastAPI/ChromaDB 저장 결과가 어긋나지 않는지 확인한다.
- FastAPI 호출 실패 시 DB 상태가 불완전하게 남지 않는지 확인한다.
