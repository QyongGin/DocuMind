# 생성 모델 등록과 모델 대장

> 결정: ADR-0036(공개 목록에 없는 모델은 이 폴더의 스크립트로 등록, compose의 모델 준비 단계는 이미 등록된 모델을 내려받지 않음), ADR-0011(배포 경로·모델 대장), ADR-0034(기반 모델 A.X 4.0 Light).
> 실행 위치: 데스크탑 WSL, 저장소 루트. 맥북은 GPU compose를 쓰지 않는다.

## 1. 모델 대장

챗봇이 쓰는 모델과 그 출처를 한 곳에 적는다. 모델을 더하거나 바꾸면 이 표에 행을 더한다(이전 모델 행은 지우지 않는다).

### 직접 변환해 등록하는 모델

| Ollama 이름 | 용도 | 원본 | 원본 커밋 | 변환 도구 | 양자화·크기 | 파일 SHA256 | 라이선스 | 채팅 틀 | 등록 |
|---|---|---|---|---|---|---|---|---|---|
| `ax40light:q4km` | 운영 생성 모델(기본값) | Hugging Face `skt/A.X-4.0-Light` | `ba21c20ea1b31ded1ec3e2fb432335077dc4be98` | llama.cpp build 11312(커밋 `0c1e57098`), 이미지 `full-b11312` | Q4_K_M, 4,435,826,528바이트 | `a1681e9b6de543835c7130cfc3673813bc5dc724f64ada8fb60d37cb2999f35b` | Apache 2.0(원본 LICENSE, Qwen 2.5 고지 포함) | `ax40light/Modelfile.tmpl` | 2026-10-01(2026-10-20 이 스크립트로 다시 만들어 같은 SHA256 확인) |

### 공개 목록에서 내려받는 모델

| Ollama 이름 | 용도 | 데스크탑에 있는 판(ID) | 라이선스 |
|---|---|---|---|
| `qwen3-embedding:4b` | 임베딩(색인·질문) | `df5bd2e3c74c` | Apache 2.0 |
| `gemma4:12b-it-qat` | 비교 기준 생성 모델 | `38044be4f923` | Apache 2.0 |

- 모델 준비 단계는 이미 등록된 모델을 다시 내려받지 않으므로 위 판이 그대로 남는다. 공개 목록의 새 판을 쓰려면 일부러 `ollama pull`하고, 임베딩이면 재색인, 생성 모델이면 개발셋 짝 비교를 한 뒤 이 표를 고친다.

## 2. A.X를 처음 등록하기

새 데스크탑이나 Ollama 볼륨을 새로 만든 뒤 한 번 한다. 원본 약 14.5GB를 내려받고 약 8분 걸린다.

1. compose를 올린다. A.X가 아직 없으면 모델 준비 단계가 "모델을 준비하지 못함"을 남기고 실패해 AI 서버는 뜨지 않지만, Ollama는 떠 있다.

   ```bash
   docker compose --project-name documind_desktop -f docker-compose.yml -f docker-compose.gpu.yml --env-file .env up -d --build
   ```

2. 공식 원본을 4비트 GGUF로 바꾼다. 끝에 "모델 대장의 SHA256과 같다"가 나와야 한다.

   ```bash
   deploy/models/convert.sh deploy/models/ax40light
   ```

3. 채팅 틀과 함께 Ollama에 등록한다. 끝에 "채팅 틀 확인: 입력 토큰 6개, 공식 틀과 같다"와 "등록함"이 나와야 한다.

   ```bash
   deploy/models/import.sh deploy/models/ax40light
   ```

4. compose를 다시 올린다. 모델 준비 단계가 "등록돼 있음, 내려받지 않음: ax40light:q4km"을 남기고 AI 서버가 뜬다.

   ```bash
   docker compose --project-name documind_desktop -f docker-compose.yml -f docker-compose.gpu.yml --env-file .env up -d
   ```

- 결과물(GGUF, 원본 LICENSE·config.json·tokenizer_config.json, SHA256SUMS, 변환 도구 판)은 Docker 볼륨 `model_work`의 `ax40light/` 폴더에 남는다. 지우지 않는다(학교에 넘길 때 쓴다).
- `.env`에 `OLLAMA_LLM_MODEL`을 직접 적었다면 그 값이 compose 기본값보다 먼저다. 기본값을 바꾸는 PR에서는 데스크탑 `.env`도 함께 확인한다.

## 3. 새 모델을 더할 때

- 이 폴더에 모델마다 폴더 하나를 만들고 `recipe.env`(이름·원본·커밋·양자화·기대 해시·기대 입력 토큰 수)와 `Modelfile.tmpl`(Ollama 채팅 틀, GGUF 경로 자리 `__GGUF__`)을 둔다. 스크립트는 모델 이름으로 갈라지지 않는다.
- 채팅 틀은 원본의 `tokenizer_config.json`에 있는 공식 틀(Jinja)과 같은 글을 만들게 Ollama Go 틀로 옮긴다. GGUF에 든 Jinja 틀을 Ollama가 그대로 쓰지 못하는 경우가 있다(2026-10 커뮤니티 GGUF에서 겪음). 기대 입력 토큰 수는 공식 틀로 "안녕하세요"를 감싼 글의 토큰 수다.
- 학습한 모델(계획 7·8단계)은 학습 서버에서 만든 GGUF를 볼륨 `model_work`의 `<NAME>/<NAME>-<QUANT>.gguf`로 옮긴 뒤 `import.sh`만 돌린다. 기반 모델과 같은 채팅 틀을 쓰고, 이전 모델을 남기도록 새 이름으로 등록한다(ADR-0011).

## 4. 학교에 넘길 때

모델 파일을 넘기는 것은 배포다. A.X 4.0 Light는 Apache 2.0이라 다음을 함께 넘긴다(`docs/rag/research/A.X-4.0-Light-사용권-조사-20261017.md` §3.3).

- 원본 LICENSE 사본(볼륨의 `ax40light/LICENSE` — 첫머리와 NOTICE 부분에 Qwen 2.5 기반 고지가 있다)
- 학습한 모델이면 수정 표시: 무엇을 어떻게 바꿨는지(학습 날짜·데이터·설정)
- SKT 상표·로고는 쓰지 않는다
