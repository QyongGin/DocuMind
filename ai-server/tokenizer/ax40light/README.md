# A.X 4.0 Light 토크나이저

AI 서버가 프롬프트 토큰 수를 세는 데 쓰는 파일이다(#274). 학습(LoRA)이 입력 길이를 잴 때 쓰는 토크나이저와 같은 파일이라,
서버가 센 값과 학습이 센 값이 같다.

| 파일 | 내용 |
|---|---|
| `tokenizer.json` | 토크나이저(Hugging Face `tokenizers` 형식) |
| `LICENSE` | 모델 저장소의 라이선스 원문(Apache License 2.0 전문과 NOTICE) |

## 출처

- 모델: [`skt/A.X-4.0-Light`](https://huggingface.co/skt/A.X-4.0-Light), 리비전 `ba21c20ea1b31ded1ec3e2fb432335077dc4be98`
  (`deploy/models/ax40light/recipe.env`의 `HF_REVISION`)
- 라이선스: Apache License 2.0. `LICENSE`는 같은 리비전의 `LICENSE` 파일 그대로다(git blob `8538327d…`가 Hugging Face 파일 목록과 같음).

## 공식 파일과 다른 점

이 `tokenizer.json`은 같은 리비전의 공식 `tokenizer.json`을 학습 도구(`transformers`의 `Qwen2Tokenizer`)가 읽어 다시 저장한
것이다. 어휘(`model.vocab`), 병합 규칙(`model.merges`), 특수 토큰(`added_tokens`), 후처리, 디코더는 공식 파일과 같고 두 칸만 다르다.

| 칸 | 공식 파일 | 이 파일 |
|---|---|---|
| `normalizer` | 없음 | NFC 정규화 |
| `pre_tokenizer` | ByteLevel(정규식 사용, 숫자를 이어서 자름) | Qwen2 정규식 Split(숫자를 한 글자씩) + ByteLevel |

공식 파일의 SHA256은 `e3973ece…f8ea44`, 이 파일은 `4050a8c9…a92c0eb`다. 학습 입력은 이 파일 규칙으로 잘리므로 서버도 이 파일로 센다.
예를 들어 「2027학년도 모집 정원 110명」은 이 파일로 12토큰, 공식 파일로 8토큰이다.

## 바꿀 때

- 생성 모델을 바꾸면 이 파일과 `LICENSE`, 위 출처, `recipe.env`의 `TOKENIZER_SHA256`을 한 PR에서 함께 바꾼다.
- 서버는 시작할 때 이 파일의 SHA256을 `recipe.env`의 `TOKENIZER_SHA256`과 견주고, 다르거나 파일이 없으면 뜨지 않는다.
- `.gitattributes`에서 이 파일을 바이너리로 다뤄 줄바꿈 변환으로 해시가 바뀌지 않게 한다.
