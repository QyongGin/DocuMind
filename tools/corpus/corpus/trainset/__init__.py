"""학습 예시 만들기(M2 6단계, 설계 `docs/rag/m2/6단계-학습예시-설계-20261021.md`).

데이터셋용 색인(ADR-0038)의 학습 몫 문서로 LoRA 학습 예시를 만든다. 단계마다 묶음 폴더에 JSONL로 남겨 이어서 돌린다.

    plan.jsonl       묶음 고르기: 예시 종류·사용자 범주·말투·질문을 만들 청크
    questions.jsonl  질문 초안(초안 모델, ADR-0040)
    attached.jsonl   근거 붙이기: 데이터셋 AI 서버 /query(평가용 옵션)의 운영 프롬프트·근거 8개·학습 전 A.X 답
    targets.jsonl    목표 답 초안(ADR-0039: 결론 → 안내 → [출처 N], 인용형은 비교용)
    checked.jsonl    자동 검사 결과(ADR-0037)

학교 글이 들어가므로 묶음 폴더는 저장소 밖(`Assets/train/<묶음>/`)에 둔다.
"""
