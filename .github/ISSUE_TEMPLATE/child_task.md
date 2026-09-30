---
name: 하위 작업 이슈
about: Epic 또는 parent issue를 해결하기 위한 작은 구현/검증 작업입니다
title: '[Task] '
labels: 'Type: Task'
assignees: ''
---

## 상위 이슈

Related #

## 문제 정의

이번 child issue가 해결하려는 실제 문제를 적습니다.

예시:
- table_fact를 문장으로만 저장해 표의 행/열/값 관계가 사라진다.
- Source preview가 검색용 합성 텍스트를 사용자 출처처럼 보여준다.
- `/debug/rag-trace`와 실제 `/query`가 서로 다른 근거를 볼 수 있다.

## 작업 범위

- [ ] 작업 항목 1
- [ ] 작업 항목 2
- [ ] 작업 항목 3

## 변경 영향 범위

이번 child issue가 어디를 바꾸고, 어디는 그대로 유지해야 하는지 적습니다.

### 변경하는 것

- 

### 변경하지 않는 것

- 업로드 흐름:
- DB schema:
- API response contract:
- 검색 순위:
- prompt:
- source 응답:

### 영향받는 데이터·엔드포인트

- 데이터:
- 엔드포인트:
- 사용자 화면:

### 회귀 확인 대상

- 기존에 통과하던 질문:
- 반례 질문:

## 완료 조건

- [ ] 문제를 재현하거나 확인할 수 있다.
- [ ] 변경 후 기대 동작을 확인했다.
- [ ] 반례를 최소 1개 확인했다.
- [ ] PR은 `develop`을 target으로 만든다.

## 검증 방법

실행할 수 있는 테스트, smoke test, 수동 확인 방법을 적습니다.

```bash
git diff --check
```

## RAG 실패 축

RAG 작업이면 관련 축을 체크합니다.

- [ ] scope_loss
- [ ] table_relation_loss
- [ ] retrieval_miss
- [ ] source_contamination
- [ ] unsupported_handling
- [ ] generation_grounding
- [ ] trace_query_drift
- [ ] index_consistency
- [ ] runtime_fit
