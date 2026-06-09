---
name: documind-rag-diagnosis
description: DocuMind RAG 실패를 진단하거나 기준 질문셋, trace/query 검증, GCP 실행 명령, RAG 구조 개선 이슈를 설계할 때 사용한다.
origin: DocuMind
tags: [documind, rag, evaluation, gcp]
version: 1.0.0
---

# DocuMind RAG 진단 스킬

## 목적

RAG 답변 실패를 단일 오답으로 보지 않고 어느 pipeline 단계에서 정보가 손실되는지 판정한다.

## 절차

1. 현재 이슈와 기준선 문서를 확인한다.
2. 실패 질문을 `parse -> cleanup -> split -> index -> retrieval -> rerank -> prompt -> source` 중 하나 이상에 매핑한다.
3. `/debug/rag-trace`와 `/query`를 분리해 retrieval 문제인지 generation grounding 문제인지 판정한다.
4. 답변 keyword뿐 아니라 page, final context, source content, forbidden evidence, unsupported answer를 함께 본다.
5. GCP 결과가 필요하면 사용자가 복붙할 수 있는 한 줄 또는 here-doc 명령과 결과 확인 명령을 함께 제공한다.
6. 결과는 질문, 기대 근거, 실제 후보, trace 상태, query 답변, 실패 단계, 실패 유형, 후속 이슈 표로 정리한다.

## 원칙

- 특정 문서명, 학과명, 전형명, 페이지 번호, 질문 예시 전용 hard coding으로 고치지 않는다.
- 먼저 PDF/DOCX/PPTX/XLSX 전반에 적용 가능한 구조 패턴을 설계한다.
- `table_fact`가 있다는 이유로 표 이해가 해결됐다고 보지 않는다. row, column, header, legend, note 관계가 보존되는지 검증한다.
- 문서가 하나일 때 우연히 맞는 답과 문서가 많아져도 유지되는 구조적 개선을 구분한다.
- 설계 판단은 공식 문서와 1차 자료를 우선 확인한다.

## 산출물

- RAG 실패 진단표
- 기준 질문셋 또는 P0/P1/P2 분류
- GCP 실행 명령과 결과 해석
- #72 기준선 대비 개선/회귀 판단
- #73 하위 구현 이슈 후보
