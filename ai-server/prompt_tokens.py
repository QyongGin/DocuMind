"""프롬프트 토큰 수를 생성 모델(A.X 4.0 Light)의 토크나이저로 센다(#274).

근거 블록에 표 전체를 넣으면 프롬프트가 문맥 길이를 넘을 수 있다. 넘는지는 글자 수 어림이 아니라 모델 저장소의 공식 토크나이저
(`tokenizer/ax40light/tokenizer.json`)로 센다. 운영 생성 모델(llama.cpp)이 자르는 규칙과 같고, 학습도 이 규칙으로 길이를 잰다.

- 파일 확인: 서버가 시작할 때 토크나이저 파일의 SHA256을 모델 설정 파일(`deploy/models/ax40light/recipe.env`)의
  `TOKENIZER_SHA256`과 견준다. 파일이 없거나 해시가 다르면 ValueError로 서버가 뜨지 않는다(조용히 다른 토크나이저로 세면
  서버가 센 길이와 생성 모델이 받는 길이가 어긋난다).
- 프롬프트 상한: 문맥 길이 − 답 상한 − 채팅 틀 토큰 수. 채팅 틀 토큰 수는 모델 설정 파일의 `EXPECTED_PROMPT_TOKENS`
  (「안녕하세요」 한 마디를 공식 채팅 틀로 감싼 입력의 토큰 수, `deploy/models/import.sh`가 Ollama 등록 때 확인)에서
  「안녕하세요」 자체의 토큰 수를 뺀 값이다. 숫자를 코드에 두지 않는다.
- 정규화: 토크나이저도 llama.cpp(Ollama)도 정규화하지 않아, 겉보기에 같은 한글이라도 완성형과 낱자 조합은 다른 토큰이 된다.
  호출자가 프롬프트를 NFC로 바꾼 뒤 세고 그 글을 생성 모델에 보내, 겉보기에 같은 글이 같은 토큰이 되게 한다(`nfc`).
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from tokenizers import Tokenizer

TOKENIZER_HASH_KEY = "TOKENIZER_SHA256"
PROMPT_TOKENS_KEY = "EXPECTED_PROMPT_TOKENS"
# deploy/models/import.sh가 채팅 틀을 확인할 때 보내는 한 마디. 모델 설정 파일의 EXPECTED_PROMPT_TOKENS가 이 글의 값이다
CHAT_TEMPLATE_PROBE = "안녕하세요"


def nfc(text: str) -> str:
    """프롬프트 글을 NFC로 정규화한다. 겉보기에 같은 한글이 같은 토큰이 되게 하고, 생성 모델에 보낼 글과 셀 글을 같게 한다."""
    return unicodedata.normalize("NFC", text)


def read_recipe(path: Path) -> dict[str, str]:
    """모델 설정 파일(셸 `source`로 읽는 KEY=VALUE 줄)을 읽는다. 주석과 빈 줄은 건너뛴다. 파일이 없으면 ValueError."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise ValueError(f"모델 설정 파일이 없다: {path}") from None
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def file_sha256(path: Path) -> str:
    """파일의 SHA256(16진수 소문자)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class PromptTokenCounter:
    """확인을 마친 토크나이저와 채팅 틀 토큰 수."""

    tokenizer: Tokenizer
    chat_template_tokens: int

    def count(self, text: str) -> int:
        """글의 토큰 수(특수 토큰 없이). 호출자가 NFC로 바꾼 글을 준다."""
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def prompt_limit(self, num_ctx: int, num_predict: int) -> int:
        """프롬프트 상한 토큰 수: 문맥 길이 − 답 상한 − 채팅 틀 토큰 수."""
        return num_ctx - num_predict - self.chat_template_tokens


def load_prompt_token_counter(tokenizer_path: Path, recipe_path: Path) -> PromptTokenCounter:
    """토크나이저 파일을 모델 설정 파일의 해시와 견주고 읽는다. 파일이 없거나 해시가 다르거나 값이 빠지면 ValueError."""
    recipe = read_recipe(recipe_path)
    expected = recipe.get(TOKENIZER_HASH_KEY, "").lower()
    if not expected:
        raise ValueError(f"모델 설정 파일에 {TOKENIZER_HASH_KEY}가 없다: {recipe_path}")
    if not tokenizer_path.is_file():
        raise ValueError(f"토크나이저 파일이 없다: {tokenizer_path}")
    actual = file_sha256(tokenizer_path)
    if actual != expected:
        raise ValueError(
            f"토크나이저 파일 해시가 모델 설정과 다르다: {tokenizer_path} {actual} != {recipe_path} {TOKENIZER_HASH_KEY}={expected}"
        )
    raw_prompt_tokens = recipe.get(PROMPT_TOKENS_KEY, "")
    try:
        prompt_tokens = int(raw_prompt_tokens)
    except ValueError:
        raise ValueError(f"모델 설정 파일의 {PROMPT_TOKENS_KEY}가 정수가 아니다: {raw_prompt_tokens!r}") from None
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    probe_tokens = len(tokenizer.encode(nfc(CHAT_TEMPLATE_PROBE), add_special_tokens=False).ids)
    chat_template_tokens = prompt_tokens - probe_tokens
    if chat_template_tokens < 0:
        raise ValueError(f"{PROMPT_TOKENS_KEY}={prompt_tokens}가 「{CHAT_TEMPLATE_PROBE}」 토큰 수 {probe_tokens}보다 작다")
    return PromptTokenCounter(tokenizer=tokenizer, chat_template_tokens=chat_template_tokens)
