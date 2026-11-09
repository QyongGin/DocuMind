# 조사 문서와 참조 지도

> 이 폴더는 결정에 쓴 외부 근거를 모아 둔 곳이다. 자료 기준(2026-10-25): **학회·학술지 심사를 통과한 논문**과 **모델을 직접 만드는 회사·기관의 공식 문서·기술 보고서**만 쓴다. 소속과 게재처는 원문에서 확인해 적는다. 기준에 맞지 않아 뺀 자료와 검색 과정은 로컬 `outputs/research/검색기록.md`에 둔다(커밋 안 함).

## 1. 근거 대장

| 짧은 이름 | 문서 | 담은 것 |
|---|---|---|
| 최신 | [학습셋-평가셋-최신실무-20261025.md](학습셋-평가셋-최신실무-20261025.md) | 학습셋·평가셋 제작 실무, 모델 제작사 공식 자료, 약관 — 자료 [1]~[27] |
| 검토 | [학습데이터-사람검토-실무조사-20261021.md](학습데이터-사람검토-실무조사-20261021.md) | 학습 데이터·평가에서 사람 검토가 남는 자리 — 자료 1~8 |
| 제작 | [학습셋-제작-실무조사-20261021.md](학습셋-제작-실무조사-20261021.md) | 근거 기반 답변 학습셋 만드는 법 — 자료 1~6 |
| 시점 | [시점-혼동-위험-조사-20261029.md](시점-혼동-위험-조사-20261029.md) | 지난 판 근거로 답하는 위험, 학습 예시 근거 시점 맞추기, 오늘 날짜·게시일 보이기 — 자료 1~20(논문 10, 모델 제작사 공식 문서 9, 학회 공지 1) |
| 탈락 | [학습데이터-탈락원인-해결방안-조사-20261030.md](학습데이터-탈락원인-해결방안-조사-20261030.md) | 학습 예시 탈락 원인별 해결 방법, 초안 모델 크기, Claude 출력으로 학습하는 일에 관한 Anthropic 도움말·사용 정책·약관 — 자료 1~14(공식 문서 6, 논문 8) |
| 초안 | [초안모델-로컬후보-조사-20261031.md](초안모델-로컬후보-조사-20261031.md) | 학습 예시 초안 모델 후보(데스크탑 GPU 12GB·학습 서버 24GB), 라이선스의 출력 사용 조항, 초안 모델을 고르는 기준 — 자료 1~15(공식 문서 11, 논문 4) |
| 방해 | [방해근거-학습데이터-구성-조사-20261109.md](방해근거-학습데이터-구성-조사-20261109.md) | 근거 속 비슷한 다른 사실 오답을 줄이는 학습 데이터 구성(방해 문서 학습, 거절 예시 비율과 과잉 거절, 근거 인용·풀이) — 자료 1~14(논문 13, 공식 문서 1) |

## 2. 참조 지도 — 우리 프로젝트의 어디에 어느 자료의 어느 부분을 썼나

> M2 6단계(학습 데이터) 결정부터 정리했다. 표의 [최신 N]·[검토 N]·[제작 N]·[시점 N]은 위 근거 대장의 번호다.

### 자료 기준

| 프로젝트 부분 | 자료 | 자료의 어느 부분 | 가져온 것 |
|---|---|---|---|
| 자료 기준(이 문서 머리말) | ACL 공식 소개, Google Scholar Metrics, Google Research 블로그 [최신 17] | ACL 소개 문장, 계산언어학 분야 h5-index 순위(ACL 236·EMNLP 218), "Google at ACL 2021" | 학회의 신뢰도를 제3자 지표로 확인하는 방법 |

### 학습 데이터 결정(ADR)

| 프로젝트 부분 | 자료 | 자료의 어느 부분 | 가져온 것 |
|---|---|---|---|
| ADR-0037 사람 검토 범위 | Nemotron-4 340B 기술 보고서(NVIDIA) [검토 1] | 초록 "over 98% of data used in our model alignment process is synthetically generated" | 대량 생성은 모델이 한다 |
| | Tülu 3 기술 보고서(AI2) [검토 2] | 선호 데이터 절 — 여러 모델 답을 LLM 판정으로 짝 비교 | 판정도 모델이 한다 |
| | Anthropic "Create strong empirical evaluations" [검토 3] | 채점 방법: 사람 채점 "Avoid if possible", LLM 채점 "Test to ensure reliability first, then scale" | 사람은 기준을 정하고 판정자를 검증하는 자리 |
| | Shankar 외, ACM UIST 2024 [검토 4] | 기준 표류(criteria drift) 실험 결과 | 사람 표본을 첫 묶음에 둔다 |
| | Bavaresco 외, ACL 2025 [검토 5] | 결론 "LLMs should be carefully validated against human judgments before being used as evaluators" | Claude 판정을 사람과 나란히 대조 |
| | ChatQA, NeurIPS 2024(NVIDIA) [검토 6] | 사람 데이터 대 합성 데이터 비교, 답없음 문항이 많은 평가셋 결과 | 사람 표본에 거절 예시를 반드시 넣는다 |
| | Gekhman 외, EMNLP 2024(Google Research·Technion) [검토 7] | 모르던 사실을 담은 예시가 지어내기를 늘린다는 결과 | 근거에 없는 값을 자동 검사로 먼저 거른다 |
| ADR-0039 목표 답 모양 | Anthropic "Reduce hallucinations" [최신 5] | "Use direct quotes for factual grounding" | 1회차에서 인용형(나)과 비교 |
| | ChatQA [검토 6] | 답없음 예시의 정답을 정해진 거절 문장 하나로 | 운영 거절 문장 하나로 가르친다 |
| ADR-0040 초안 모델(Gemma) | Anthropic 소비자 약관 §3, 상업 약관 D.4 [최신 23·24] | 경쟁 상품·모델 개발 금지 문장 | Claude로 학습 데이터를 만들지 않는다 |
| | Li 외 "Preference Leakage", ICLR 2026 [최신 22] | 초록 "the bias of judges towards their related student models" | 초안 모델과 판정 모델을 다른 계열로 |
| | DataMorgana, ACL 2025 Industry(TII) [최신 20] | 질문 범주와 분포를 설정해 생성 | 사용자 범주 × 질문 유형 비율을 먼저 정한다 |
| | Know Your RAG, COLING 2025(IBM) [제작 3] | 데이터셋을 라벨로 특징짓고 라벨을 겨냥해 생성 | 유형별 개수를 맞춘다 |
| | Kambhatla 외, EMNLP 2025 Findings [최신 21] | 세부 페르소나 이득은 길이 지정과 비슷 | 사용자 범주는 간단히, 길이·말투를 지시 |
| ADR-0041 종류는 받은 근거로 | Anthropic "Reduce hallucinations" [최신 5] | "only use information from provided documents", 정보가 없으면 "I don't have enough information" | 답할지 거절할지는 받은 문서가 정한다 |
| | OpenAI "Supervised fine-tuning" [최신 6] | "Whatever prompts and outputs you expect in your application, as realistic as possible" | 학습 예시는 운영 입력과 같게 |
| | UAEval4RAG, ACL 2025(Salesforce) [최신 1] | §3.2 문서에 없음 질문 만들기 — "each chunk is checked to confirm it does not contain the answer" | 질문을 만든 뒤 실제 검색 결과로 종류를 확정 |
| ADR-0042 A.X 아는 정도 | Llama 3 기술 보고서(Meta) [최신 15] | §4.3.6 knowledge probing("know what it knows"), §4.2.2 여러 답 중 보상 모델이 고름 | 학생 모델 답을 여러 번 받아 채점 |
| | Gekhman 외, EMNLP 2024 [검토 7] | 모델이 맞히는 정도로 예시를 Known/Unknown으로 가름, Unknown을 "I don't know"로 바꾸면 과적합이 줆 | 예시마다 아는 정도를 기록 |
| | Knowledge-Weighted FT, Findings of EMNLP 2026(NAVER Cloud·서울대·KAIST) [최신 4] | 여러 번 샘플링한 아는 정도로 학습 신호 조절 | 7단계에서 학습 비중 조절 검토 |
| | Anthropic "Reduce hallucinations" [최신 5] | "Best-of-N verification" — 같은 질문 여러 번, 엇갈리면 환각 신호 | 여러 번 받기 |
| | TRL `DPOTrainer` 문서(Hugging Face) [최신 10] | `ref_model`이 없으면 "the initial policy" | 틀린 답을 '나쁜 답'으로 둔 선호 학습이 모델 한 벌로 가능 |
| | Qwen3 기술 보고서(Qwen Team) [최신 2] | §4.7·표 21 온정책 증류(RL 17,920 대 1,800 GPU 시간) | 방향의 근거. 토크나이저가 달라 그대로는 못 씀(버린 대안) |
| ADR-0043 거절 20% | OpenAI "Fine-tuning best practices" [최신 11] | 데이터 균형 — 거절이 운영보다 많으면 "the model will refuse too often" | 거절 비율을 평가셋 비율 쪽으로 낮춘다 |
| ADR-0044 실제 사용자 말투 | DataMorgana [최신 20] | 서론 "may not be realistic (e.g., contain too many technical terms)", 표 1 Phrasing "concise-and-natural" | 짧은 구어·검색어형, 공식 명칭 베끼지 않기 |
| | OpenAI "Supervised fine-tuning" [최신 6] | "as realistic as possible" | 같음 |
| | Kambhatla 외 [최신 21] | "significantly less diverse than human-written ones" | 말투·길이를 바꿔 지시 |
| | Preference Leakage [최신 22], Anthropic·OpenAI·Gemini 약관 [최신 23·25·26] | 위와 같음 | 초안 모델을 상용 모델로 바꾸지 않는다(버린 대안) |
| ADR-0045 모호한 질문 | — | — | 첫 묶음 실측과 결정(외부 자료 없음) |

### 점검 문서·남은 결정

| 프로젝트 부분 | 자료 | 자료의 어느 부분 | 가져온 것 |
|---|---|---|---|
| 점검 문서 문제 4(서식 청크 필터를 만들지 않음) | Llama 3 기술 보고서 [최신 19] | §3.1.1 줄 단위 중복 제거 — 자주 나오는 좋은 글까지 지운다는 한계 | 측정해 보니 안내 줄까지 빠져 버린 이유의 뒷받침 |
| 점검 문서 문제 6(양 정하기) | OpenAI "Fine-tuning best practices" [최신 11] | 예시를 두 배로 늘릴 때마다 비슷하게 좋아진다 — 절반과 전체를 견줘 가늠 | 1회차에서 100·200 비교(7단계) |
| 안내 빠짐 고치는 법 A·B(결정 대기) | Anthropic "Prompting best practices – Chain complex prompts" [최신 18] | "The most common chaining pattern is self-correction: generate a draft → … review it against criteria → … refine" | A(자기 수정)·B(단계 나누기) 후보 |
| 사람 30개 표본 뒤 판정 확대 | OpenAI "Evaluation best practices" [최신 13], Anthropic "Demystifying evals" [최신 7] | 판정 모델은 "consistently agrees with human annotations" 뒤에 늘린다, "closely calibrated with human experts" | 어긋남 1개 이하일 때만 나머지를 Claude로 |
| 학습 예시 근거의 시점(결정 대기, 시점 §6) | HoH, ACL 2025(중국과학기술대) [시점 1] · Re³, ACL 2026(중국과학기술대·iFLYTEK) [시점 2] | 옛 정보가 지금 정보와 함께 있어도 정답률을 떨어뜨림 · 옛 판을 걸러 내면 평균 +9.7%, 날짜로 거르는 검색은 날짜가 틀리면 놓침 | 재료보다 뒤 판·만료된 판을 근거에서 빼되, 대장 유효 기간부터 바로잡는다 |
| | FreshLLMs, Findings of ACL 2024(Google) [시점 7] · Dhingra 외, TACL 2022(Google) [시점 8] · RetrievalQA, Findings of ACL 2024(시드니공대·리버풀대) [시점 9] · Meta·Anthropic 공식 문서 [시점 11·12] | 근거마다 날짜, "As of today {current_date}" · 입력에 "year: 2018" · "Today is current_date()" · "Today Date", "The current date is" | 운영·학습 프롬프트에 오늘 날짜 줄과 근거 게시일 |
| | Test of Time, ICLR 2025(Google) [시점 10] · FreshLLMs 제거 실험 [시점 7] | 시간 추론 오류, 사실 순서로 58.82~71.95% · 날짜를 뺀 차이 1% 미만 | 반대 근거 — 개발셋·표본으로 먼저 잰다 |
| | Longpre 외, EMNLP 2021(Apple·UC Irvine) [시점 4] · Context-DPO, Findings of ACL 2025(중국과학원대·Microsoft) [시점 5] · SituatedQA, EMNLP 2021(UT Austin) [시점 3] | 근거 속 답을 바꾼 예시로 외운 답 29.5% → 2.6% · DPO로 근거 충실도 35~280% · 과거 데이터로 학습한 모델이 지금 질문에서 약 15점 낮음 | 학습 뒤 시점 시험, 옛 값을 말하면 7단계에서 근거 따르기 학습 |
| | Anthropic Long context prompting [시점 15] · OpenAI Retrieval 가이드·Model Spec [시점 16·17] · Google Vertex AI Search·Gemini 3 가이드 [시점 18·19] · Microsoft Azure AI Search [시점 20] | 문서마다 메타데이터 · 날짜 범위로 거르기, "As of January 2025", 확신 없는 틀린 답이 가장 나쁨 · 최신성 가산점, "For more recent information, use the Search Grounding tool" · "not a hard filter", 날짜 값 품질 | 학습은 거르기, 운영 최신 우대는 가산점도 선택지(E), 답에 기준 시점, 지금 판 없으면 단정 금지 |

### 평가 방식(유지 근거)

| 프로젝트 부분 | 자료 | 자료의 어느 부분 | 가져온 것 |
|---|---|---|---|
| 평가셋·채점 방식 | Anthropic "Demystifying evals for AI agents" [최신 7] | "20-50 simple tasks drawn from real failures", 두 전문가가 같은 판정, 채점 세 종류 | 운영 뒤 실제 실패를 평가셋에 더한다 |
| | OpenAI "Evaluation best practices" [최신 13] | 로그에서 평가 문항 캐기, 합성 데이터로 엣지·적대 사례, 사람으로 자동 채점 보정 | 같음 |
| 학습 전후 비교 | van Elburg 외, ECML-PKDD 2025 워크숍(암스테르담대 등) [최신 8] | 합성 벤치마크는 생성 모델 비교에서 순위가 흔들린다 | 규칙 채점(필수 사실)과 손대지 않은 테스트셋 유지 |
| | Rahmani 외, CIKM 2025(UCL·Microsoft) [제작 6] | 합성 데이터 편향은 절대 점수에 크고 상대 비교에 작다 | 같은 문항 짝 비교 유지 |
| 결과 구간 표기 | Bowyer 외, ICML 2025(브리스톨대·옥스퍼드대) [최신 9] | 수백 문항 미만에서 CLT 오차 막대가 너무 좁다 | 정확 검정·베이즈 구간 |
| 6단계 설계(거절·인용 학습) | Trust-Align, ICLR 2025 구두(싱가포르기술디자인대·DSO) [제작 5] | 27개 모델 중 26개가 기준선보다 좋음, LLaMA-3-8B 수치 | 거절·인용 학습이 8B에서도 효과 |

### 코드

| 코드 | 결정 |
|---|---|
| `tools/corpus/corpus/trainset/checks.py` `decide_kind` | ADR-0041 |
| `pipeline.run_probe`, `checks.probe_score` | ADR-0042 |
| `plan.ROUND1` | ADR-0043 |
| `prompts.STYLE_RULES`, `plan.STYLES`, `judge.PROMPT` 6번 | ADR-0044 |
| `evidence.guidance_candidates` | 첫 묶음 실측(Claude 탈락 16개 중 안내 빠짐 7) — 외부 자료가 아닌 우리 설계 |

## 3. 아직 이 기준으로 다시 보지 않은 문서

2026-10-25 이전 문서는 자료 기준을 정하기 전에 썼다. 프리프린트·업체 자료가 남아 있을 수 있어 차례로 다시 본다: ADR-0026(EnterpriseRAG-Bench 프리프린트, Vectara 리더보드, SMU 학술지), 이 폴더의 2026-10-01~10-17 조사 문서(기반 모델·라이선스·검색 개선·RAG 사례 등), `docs/project/설계6단계-결정근거대장-20261001.md`.
