# A.X 4.0 Light를 인하공전 챗봇에 써도 되는가 — 사용권 조사 (2026-10-17)

> 목적: 기반 모델을 A.X 4.0 Light로 정하면서(2026-10-17 사용자 결정, ADR-0033), 저작권·상업 이용·학교 공식 챗봇 사용·학습(파인튜닝)·학습한 모델 인계 조건을 원문으로 확인한다.
> 방법: 2026-10-17 Hugging Face 저장소의 원문 파일(LICENSE, README, 저장소 정보 API)을 직접 열어 읽었다(검색 요약을 쓰지 않음). 2026-10-18 원문 사본·캡처·SKT 공식 발표·72B 대조를 §0에 더했다. 법·규제(AI 기본법, 중국 계보 모델 조치, 개인정보)는 `후보모델-공식챗봇-사용가능-심층조사-20261014.md`를 이어받는다.
> **법률 자문이 아니다.** 학교 법무 검토 때 확인할 질문은 §5에 모았다.

## 0. 증거 묶음 (발표용, 2026-10-18 보강)

원문 사본은 `evidence/A.X-4.0-Light-20261018/`(이 폴더, 커밋), 화면 캡처는 `outputs/ax-license-evidence-20261018/`(로컬)에 있다. 아래 인용은 모두 2026-10-18 원문 페이지에서 그대로 옮겼다.

| # | 증거 | 원문 인용 | 링크 | 사본·캡처 |
|---|---|---|---|---|
| 1 | A.X 4.0 Light LICENSE 파일(SKT) | "Built with Qwen 2.5 — original model by Alibaba Cloud, licensed under the Apache License 2.0." / "all files in this repository (including modified model weights and tokenizer files) are distributed under the terms of the Apache License, Version 2.0" | [LICENSE](https://huggingface.co/skt/A.X-4.0-Light/blob/main/LICENSE) · [raw](https://huggingface.co/skt/A.X-4.0-Light/raw/main/LICENSE) | `A.X-4.0-Light-LICENSE.txt` · 캡처 01 |
| 2 | 모델 카드·저장소 태그(SKT) | README: "The `A.X 4.0 Light` model is licensed under `Apache License 2.0`." / 저장소 태그 `license:apache-2.0`(저장소 sha `ba21c20e…`, 2025-07-23) | [모델 카드](https://huggingface.co/skt/A.X-4.0-Light) · [저장소 정보 API](https://huggingface.co/api/models/skt/A.X-4.0-Light) | 캡처 02 |
| 3 | 바탕 모델 Qwen2.5-7B LICENSE(Alibaba) | Apache License 2.0 전문, 끝에 "Copyright 2024 Alibaba Cloud / Licensed under the Apache License, Version 2.0" / 태그 `license:apache-2.0` | [LICENSE](https://huggingface.co/Qwen/Qwen2.5-7B/blob/main/LICENSE) · [API](https://huggingface.co/api/models/Qwen/Qwen2.5-7B) | `Qwen2.5-7B-LICENSE.txt` · 캡처 03 |
| 4 | Apache 2.0 제2조(허락 범위) | "a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable copyright license to reproduce, prepare Derivative Works of, publicly display, publicly perform, sublicense, and distribute the Work and such Derivative Works" — 상업·비상업 구분 없음 | [apache.org](https://www.apache.org/licenses/LICENSE-2.0) | 1·3의 사본에 포함 |
| 5 | **대조: A.X 4.0 표준 모델(72B)은 다르다** | LICENSE가 "Qwen LICENSE AGREEMENT Release Date: September 19, 2024"이고 "4. Restrictions: If you are commercially using the Materials, and your product or service has more than 100 million monthly active users, you shall request a license from us." 저장소 태그 `license:other` | [72B LICENSE](https://huggingface.co/skt/A.X-4.0/blob/main/LICENSE) · [API](https://huggingface.co/api/models/skt/A.X-4.0) | `A.X-4.0-72B-LICENSE-발췌.txt` · 캡처 04 |
| 6 | SKT 공식 발표(뉴스룸, 2025-07-03) "SK텔레콤, 에이닷 엑스 4.0 지식형 모델 오픈소스로 공개" | "허깅페이스(Hugging Face)를 통해 A.X 4.0의 표준 모델과 경량 모델 2종을 공개했다" / "표준 모델은 720억 개(72B), 경량 모델은 70억 개(7B)의 매개변수" / "오픈소스 모델인 Qwen2.5에 방대한 한국어 데이터를 추가로 학습" | [news.sktelecom.com/213534](https://news.sktelecom.com/213534) | 캡처 06 |
| 7 | SKT 공식 발표(뉴스룸, 2025-07-29) | "해당 모델들은 학술 연구나 상업 이용 등에 자유롭게 활용 가능하다"(그날 공개한 A.X Encoder·A.X 4.0 VL Light에 대한 문장. VL Light는 "70억 개(7B) 매개변수의 A.X 4.0 Light 모델을 기반으로 개발") | [news.sktelecom.com/214055](https://news.sktelecom.com/214055) | 캡처 05 |
| 8 | 언론 보도의 '상용화 제한'(바이라인네트워크, 2025-07-03) | "이 모델을 이용한 상용화는 제한된다. 알리바바의 큐원 모델 라이선스에 따라 월 1억 이상 사용자를 대상으로 상용 제품이나 서비스를 제공할 경우 알리바바로부터 별도 라이선스를 확보해야 한다." — 기사는 72B·7B를 구분하지 않았지만, 이 조항은 72B의 Qwen LICENSE(5번)에만 있고 7B Light의 Apache 2.0에는 없다 | [byline.network](https://byline.network/2025/07/3-280/) | — |
| 9 | 제3자 보존본(Wayback Machine) | A.X 4.0 Light LICENSE 페이지 2025-11-19 스냅샷 | [web.archive.org](http://web.archive.org/web/20251119053057/https://huggingface.co/skt/A.X-4.0-Light/blob/main/LICENSE) | — |

### 0.1 이 증거가 얼마나 확실한가

| 물음 | 답 | 근거 |
|---|---|---|
| "Apache 2.0"은 SKT가 직접 밝힌 것인가 | **그렇다.** Hugging Face의 `skt` 조직은 SK Telecom 인증 조직이고, LICENSE·README는 그 저장소에 SKT AI Model Lab이 올린 파일이다(README `developers: SKT AI Model Lab`, 업로더 jackyoung96, 파일 커밋 c0e88ae). 라이선스는 법적으로 이 파일이 원본이다 | 캡처 01·02, 저장소 정보 API |
| SKT 뉴스룸·GitHub에도 "Apache 2.0"이라고 써 있나 | **아니다.** 뉴스룸 보도자료(2025-07-03)는 "오픈소스로 공개"·"허깅페이스를 통해 2종 공개"까지만 쓰고 라이선스 이름은 없다. GitHub `SKT-AI/A.X-4.0`에는 LICENSE 파일이 없다(404, 저장소 정보의 license가 비어 있음). 그래서 "공식 사이트가 Apache 2.0이라고 말한다"가 아니라 **"SKT가 올린 라이선스 파일이 Apache 2.0이다"**로 말해야 정확하다 | news.sktelecom.com/213534, api.github.com/repos/SKT-AI/A.X-4.0 (2026-10-18) |
| 상업 이용이 허용된다는 문장이 SKT 글에 있나 | 2025-07-29 보도자료에 "해당 모델들은 학술 연구나 상업 이용 등에 자유롭게 활용 가능하다"가 있으나, 그 문장의 직접 대상은 그날 공개한 A.X Encoder·A.X 4.0 VL Light다(VL Light는 4.0 Light 기반). 4.0 Light 자체의 상업 이용 허용은 **Apache 2.0 제2조**(사용 목적 제한 없음)에서 나온다 | §0 표 4·7 |
| 바탕 모델 쪽 제약은 없나 | 없다. Qwen2.5-7B는 Apache 2.0이다. "월 1억 사용자" 조항은 Qwen2.5-72B 계열의 Qwen LICENSE에 있고, A.X 4.0 **72B**가 그 라이선스다 | §0 표 3·5, 캡처 03·04 |
| 확신도 | 라이선스 자체: **높음**(원문, 두 저장소 모두 확인). "학교 챗봇에 써도 되는가"의 법적 판단: 법률 자문이 아니므로 M5 전 법무 검토(§5) | |

### 0.2 실제로 쓰이고 있는가 (2026-10-18 조사)

| 종류 | 확인한 것 | 출처 |
|---|---|---|
| SKT 자체 상용 서비스 | A.X 4.0을 2025년 5월부터 에이닷 통화 요약에 적용(보도자료 원문: "SKT는 이미 A.X4.0을 지난 5월 에이닷 통화 요약에 적용, 성공적으로 활용하고 있으며"). 모델 크기(72B·7B)는 명시되지 않았다. "하루 1000만 건" 규모는 SKT 관계자 발언(언론 인용, 회사 주장) | [뉴스룸 213534](https://news.sktelecom.com/213534), [딜사이트](https://dealsite.co.kr/articles/143106) |
| SKT 파생 제품 | A.X 4.0 VL Light(멀티모달)가 "70억 개(7B) 매개변수의 A.X 4.0 Light 모델을 기반으로 개발" — SKT가 Light를 자기 제품의 바탕으로 쓴 사례 | [뉴스룸 214055](https://news.sktelecom.com/214055) |
| 공개 생태계(Hugging Face, 2026-10-18 열람) | 지난 한 달 내려받기 73,034회. 모델 트리: 어댑터 14 · 미세조정 16 · 양자화 15. 이름에 `A.X-4.0-Light`가 든 제3자 저장소 84개(GGUF 변환, 금융 라우터, 대학 과제로 보이는 LoRA 다수). 이 모델을 쓰는 Space 3개 | [모델 카드](https://huggingface.co/skt/A.X-4.0-Light), [검색 API](https://huggingface.co/api/models?search=A.X-4.0-Light&limit=100) |
| 외부 기업의 상용 도입 | **공개된 사례를 찾지 못했다.** 기업용 솔루션 '에이닷 비즈'에 A.X 4.0 도입을 "검토 중"이라는 2025년 보도만 있고 결과는 미확인 | 언론 검색(2026-10-18) |

발표에서는 "SKT가 자사 서비스에 쓰는 모델이고, 공개 뒤 월 7만 회 내려받기와 파생 모델 45개가 있다. 타사 상용 도입 사례는 공개된 것이 없다"로 말한다. Apache 2.0은 선례가 있어야 쓸 수 있는 라이선스가 아니다.

**발표 한 줄**: A.X 4.0 Light는 SKT가 Apache 2.0으로 공개한 모델이고 바탕 모델 Qwen2.5-7B도 Apache 2.0이라, 학교 공식 서비스·상업 이용·학습·학습한 모델 인계가 모두 허용된다. 같은 A.X 4.0이라도 72B 표준 모델은 Qwen 라이선스(월 1억 사용자 조항)라 다르다 — 우리는 7B Light를 쓴다.

**지킬 것 한 줄**: 학교에 넘길 때 LICENSE 사본·Qwen 2.5 고지(NOTICE)·수정 표시를 함께 넘기고, SKT 상표·로고는 쓰지 않는다. 틀린 답의 책임은 운영 쪽에 있다(보증 없음).

## 1. 결론

| 쓰임 | 가능 여부 | 지킬 것 | 근거 |
|---|---|---|---|
| 학교 공식 챗봇(무료 서비스) | 가능 | AI 사용 고지(AI 기본법 제31조), 보증 없음 안내 | [원문] Apache 2.0 제2조(사용 목적 제한 없음), 제7조 |
| 상업 이용 | 가능 | 위와 같음 | [원문] Apache 2.0 제2조 |
| 학습(LoRA)·수정 | 가능 | 수정한 파일에 수정했다는 표시 | [원문] 제2조 '파생 저작물 작성', 제4조 (b) |
| 학습한 모델을 학교에 넘김(배포) | 가능 | LICENSE 사본, NOTICE(Qwen 2.5 고지) 유지, 수정 표시 | [원문] 제4조 (a)~(d), LICENSE의 NOTICE 절 |
| 답만 서비스로 제공(가중치를 넘기지 않음) | 가능 | 배포 조건(제4조)은 생기지 않음 | [판단] 제4조는 복제·배포에 붙는 조건이고, 네트워크 서비스 조항이 없다 |
| A.X 출력으로 학습 데이터 만들기 | 막는 조항 없음 | — | [원문] LICENSE 전문에 출력 사용 제한이 없다(EXAONE 'NC' 라이선스와 다름) |
| SKT 상표·로고 사용 | 허락 없이는 불가 | 챗봇 이름·화면에 SKT·A.X 로고를 쓰지 않음, 모델 이름은 출처 고지 문구로만 | [원문] LICENSE의 TRADEMARK 절, Apache 2.0 제6조 |

확신도: 높음 — 라이선스가 Apache 2.0 하나로 단순하고, 바탕 모델(Qwen2.5-7B)도 Apache 2.0임을 원문으로 확인했다. '서비스만 제공하면 배포 조건이 없다'는 해석만 [판단]이다.

## 2. 확인한 원문 (2026-10-17 열람)

| 무엇 | 확인한 내용 |
|---|---|
| 저장소 정보(`api/models/skt/A.X-4.0-Light`) | 공개(gated 아님), 태그 `license:apache-2.0`, 커밋 `ba21c20e…`, 마지막 수정 2025-07-23, 구조 `Qwen2ForCausalLM` |
| LICENSE 첫 부분 | 저작권자 SK Telecom(2025). Qwen 2.5(Alibaba Cloud, Apache 2.0)로 만들었다고 밝히고, 수정한 가중치·토크나이저를 포함한 저장소 파일 전체를 Apache 2.0으로 배포한다고 적었다 |
| LICENSE의 NOTICE 절 | Apache 2.0 제4조 (d)의 고지: Alibaba Cloud가 개발한 Qwen 2.5로 만든 제품이라는 문구 |
| LICENSE의 TRADEMARK 절 | 'SK Telecom'과 로고는 SKT 상표이고, 이 라이선스로 사용 허락을 주지 않는다(사전 서면 동의 필요) |
| LICENSE 본문 | Apache License 2.0 전문 |
| README(모델 카드) | 라이선스 Apache 2.0. 2025-07-03 공개, Qwen2.5에 한국어 데이터를 더 학습한 모델, Light는 7B·최대 16,384토큰. 문의처 a.x@sk.com |
| 바탕 모델 `Qwen/Qwen2.5-7B` | LICENSE가 Apache License 2.0 전문, 태그 `license:apache-2.0` |

Apache 2.0에서 우리 쓰임에 걸리는 조항(원문 apache.org):

- 제2조 저작권 허락: 복제, 파생 저작물 작성, 공개 표시·실행, 재허락, 배포를 허락한다. 사용 목적(상업·비상업)을 가리지 않는다.
- 제3조 특허 허락.
- 제4조 재배포 조건: (a) 라이선스 사본을 함께 준다, (b) 수정한 파일에 수정했다는 눈에 띄는 표시를 단다, (c) 원래 저작권·특허·상표·출처 고지를 유지한다, (d) NOTICE 파일이 있으면 그 고지를 함께 넣는다.
- 제6조 상표: 상호·상표 사용은 허락하지 않는다(출처를 밝히는 합리적 사용은 예외).
- 제7조 보증 없음, 제8조 책임 제한.

## 3. 우리 쓰임별 정리

### 3.1 학교 공식 챗봇·상업 이용

사용 목적 제한이 없어 학교 공식 서비스에 그대로 쓸 수 있다. 사용료·사용자 수 제한도 없다.

### 3.2 학습(LoRA)

파생 저작물 작성이 허락되어 학습할 수 있다. 학습 데이터는 학교 문서로 만드는데, 그 이용 조건은 모델 라이선스와 별개로 ADR-0006(학교 자료 이용)·ADR-0010(학습 데이터·AWS 반출 범위)을 따른다.

### 3.3 학습한 모델을 학교에 넘길 때(인계 = 배포)

인계 패키지(ADR-0011·0012)에 다음을 넣는다.

1. Apache 2.0 LICENSE 사본(A.X 저장소의 LICENSE 파일 그대로)
2. NOTICE 고지: Qwen 2.5(Alibaba Cloud) 기반이라는 문구
3. 수정 표시: "SKT A.X 4.0 Light를 인하공업전문대학 공개 문서로 LoRA 학습함" + 학습 날짜·학습 설정 기록
4. SKT 상표·로고를 쓰지 않음

### 3.4 학습 데이터 초안을 A.X로 만들기

ADR-0010은 학습 데이터 초안을 Apache 2.0·MIT 오픈 모델로 만들게 했다. A.X 4.0 Light는 이 조건에 맞고, 출력 사용을 막는 조항이 없다. EXAONE(출력으로 다른 모델 학습 금지)과 다른 점이다.

### 3.5 이용안내와 화면

- AI 사용 사전 고지·결과 표시(AI 기본법 제31조)는 모델과 무관하게 한다(ADR-0011·0012).
- 이용안내에 "SKT A.X 4.0 Light(Apache 2.0, Qwen 2.5 기반)를 학교 문서로 학습한 모델"처럼 출처를 적는 것은 사실을 밝히는 것이라 상표 사용으로 보지 않는다[판단]. 로고는 쓰지 않는다.
- 보증 없음(제7조)이라 틀린 답의 책임은 운영 쪽에 있다 — 답 아래 출처·담당 부서 안내와 함께 둔다(ADR-0012).

## 4. 라이선스 밖에서 확인할 것

| 항목 | 정리 | 출처 |
|---|---|---|
| 중국 계보 | 바탕이 Alibaba의 Qwen2.5다. 가중치를 우리 서버에서 돌려 질문·답이 Alibaba로 가지 않는다[판단]. 정부 조치와 학교 설명 방법은 이전 조사 §3.2 | `후보모델-공식챗봇-사용가능-심층조사-20261014.md` |
| 운영 서빙 위치 | 운영은 클라우드 예정이라 학교 데이터가 기관 밖 서버로 가는 문제는 모델과 별개로 M6 전에 정한다 | ADR-0030 |
| 학습 데이터 투명성 | SKT는 한국어 42%·영어 51%·기타 7% 추가 사전 학습을 밝혔지만 데이터 세부는 공개하지 않았다 | 이전 조사 §4.1 |
| 문맥 길이 | Light는 최대 16,384토큰. 지금 운영 생성 문맥 12,288과 근거 8개 프롬프트(최대 약 9,800토큰)는 들어간다 | README, 3단계 보고서 §7 |

## 5. 학교 법무·정보보호 담당에게 물을 것

1. 학습한 모델을 학교 서버로 넘길 때 LICENSE·NOTICE 사본과 수정 표시(§3.3)로 충분한가.
2. 중국 계보 바탕 모델(Qwen2.5)에 대한 학교 내부 기준이 있는가.
3. 이용안내에 바탕 모델 이름을 적는 방식(§3.5)이 괜찮은가.

## 6. 검증 시점

- 학습한 모델을 인계 패키지에 넣을 때(M4) §3.3 목록을 다시 확인한다.
- 학교 제안 전(M5) 법무 검토에서 §5를 묻는다.
- 저장소 커밋(`ba21c20e…`)이 바뀌면 LICENSE를 다시 읽는다.

## 7. 참고

- SKT A.X 4.0 Light 저장소: https://huggingface.co/skt/A.X-4.0-Light (LICENSE, README, 저장소 정보 API, 2026-10-17 열람)
- Qwen2.5-7B 저장소: https://huggingface.co/Qwen/Qwen2.5-7B (LICENSE, 저장소 정보 API, 2026-10-17 열람)
- Apache License 2.0 원문: https://www.apache.org/licenses/LICENSE-2.0
- 이전 조사: `후보모델-공식챗봇-사용가능-심층조사-20261014.md`, `후보모델-학교챗봇-사용가능-재확인-20261013.md`, `생성모델-라이선스-및-학습데이터-조사-20261001.md`
