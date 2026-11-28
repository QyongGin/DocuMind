# A.X 4.0 Light 토크나이저

AI 서버가 프롬프트 토큰 수를 세는 데 쓰는 파일이다(#274). 모델 저장소의 공식 `tokenizer.json` 그대로이고, 운영 생성 모델
(Ollama, llama.cpp)이 입력을 자르는 규칙과 같다. 학습도 이 규칙으로 입력 길이를 잰다(#280).

| 파일 | 내용 |
|---|---|
| `tokenizer.json` | 토크나이저(Hugging Face `tokenizers` 형식) |
| `LICENSE` | 모델 저장소의 라이선스 원문(Apache License 2.0 전문과 NOTICE) |

## 출처

- 모델: [`skt/A.X-4.0-Light`](https://huggingface.co/skt/A.X-4.0-Light), 리비전 `ba21c20ea1b31ded1ec3e2fb432335077dc4be98`
  (`deploy/models/ax40light/recipe.env`의 `HF_REVISION`)
- `tokenizer.json`: 같은 리비전의 파일 그대로다. git blob `2648cf18…`가 Hugging Face 파일 목록과 같고, SHA256은 `e3973ece…f8ea44`다.
- 라이선스: Apache License 2.0. `LICENSE`는 같은 리비전의 `LICENSE` 파일 그대로다(git blob `8538327d…`가 Hugging Face 파일 목록과 같음).

## 규칙

- `normalizer`가 없다. 서버는 프롬프트를 NFC로 정규화한 뒤 세고 그 글을 생성 모델에 보낸다. 겉보기에 같은 한글(완성형과 낱자 조합)이
  같은 토큰이 되게 하려는 것이다.
- `pre_tokenizer`는 ByteLevel(GPT-2 정규식)이라 이어진 숫자를 묶어 자른다. 예: 「2027학년도 모집 정원 110명」은 8토큰이다.
- `transformers` 5.8.0 이후의 `AutoTokenizer`로 읽어 다시 저장하면 NFC와 숫자를 한 글자씩 자르는 규칙이 들어간 다른 파일이 된다.
  그 파일을 넣지 않는다.

## 바꿀 때

- 생성 모델을 바꾸면 이 파일과 `LICENSE`, 위 출처, `recipe.env`의 `TOKENIZER_SHA256`을 한 PR에서 함께 바꾼다.
- 서버는 시작할 때 이 파일의 SHA256을 `recipe.env`의 `TOKENIZER_SHA256`과 견주고, 다르거나 파일이 없으면 뜨지 않는다.
- `.gitattributes`에서 이 파일을 바이너리로 다뤄 줄바꿈 변환으로 해시가 바뀌지 않게 한다.
