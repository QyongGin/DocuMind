---
name: documind-source-research
description: DocuMind 설계 판단, 기술 선택, RAG/배포/보안/성능 설명에 필요한 공식 문서와 1차 자료를 찾고 근거 기반으로 요약할 때 사용한다.
origin: DocuMind
tags: [documind, research, sources, evidence]
version: 1.0.0
---

# DocuMind 근거 조사 스킬

## 목적

설계 판단과 기술 설명을 신뢰도 높은 자료에 연결한다. 근거 없이 "업계에서 이렇게 한다", "대기업도 이렇게 한다"라고 쓰지 않는다.

## 언제 사용하는가

- RAG 구조, parser, chunking, retrieval, reranking, grounding 설계를 설명할 때
- 배포, 보안, 성능, 운영, 테스트 전략을 정할 때
- 최신 버전, 라이선스, 공식 권장 방식이 중요할 때
- 사용자가 "신뢰도 높은 자료", "공식 문서", "논문", "기술 리포트"를 요구할 때

## 자료 우선순위

1. 해당 제품/라이브러리 공식 문서
2. OpenAI, Google, AWS, Microsoft, NVIDIA, IBM, Anthropic 같은 1차 기술 문서
3. Google SRE, AWS Well-Architected, Microsoft Azure Architecture Center 같은 운영/아키텍처 가이드
4. 논문 또는 기술 리포트
5. 블로그와 개인 글

## 절차

1. 판단하려는 claim(주장)을 한 문장으로 쓴다.
2. claim이 최신성, 보안, 성능, 비용, 라이선스와 관련되면 반드시 최신 자료를 확인한다.
3. 검색 시 공식 문서와 1차 자료를 먼저 연다.
4. 자료가 말하는 사실과 DocuMind에 적용한 inference(추론)를 구분한다.
5. 서로 충돌하는 자료가 있으면 실제 코드/테스트 결과와 더 직접적인 공식 문서를 우선한다.
6. 최종 설명에는 링크와 함께 "이 자료가 DocuMind 판단에 어떻게 연결되는지"를 적는다.

## 출력 형식

```markdown
## 확인한 주장
- 주장:

## 참고 자료
| 자료 | 신뢰도 | 핵심 내용 | DocuMind 적용 |
|---|---|---|---|
| 공식 문서 링크 | 공식/1차 | 요약 | 적용 판단 |

## 결론
- 선택:
- 이유:
- 한계:
- 후속 검증:
```

## 주의

- 자료 내용을 과장하지 않는다.
- 블로그 글 하나만으로 설계 결정을 확정하지 않는다.
- 외부 자료는 방향을 잡는 근거이고, 최종 판단은 DocuMind 코드와 테스트 결과로 검증한다.
- OpenAI API나 Codex 자체 사용법은 전역 `openai-docs` 스킬과 공식 OpenAI 문서를 우선한다.
