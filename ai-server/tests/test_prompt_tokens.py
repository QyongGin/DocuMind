"""프롬프트 토크나이저 파일 확인과 토큰 세기(#274).

서버는 시작할 때 `tokenizer/ax40light/tokenizer.json`의 SHA256을 모델 설정 파일(`deploy/models/ax40light/recipe.env`)의
`TOKENIZER_SHA256`과 견주고, 파일이 없거나 해시가 다르면 뜨지 않는다. 프롬프트 상한은 문맥 길이 − 답 상한 − 채팅 틀 토큰 수다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

import main
import prompt_tokens
from prompt_tokens import load_prompt_token_counter, nfc

AI_SERVER_DIR = Path(__file__).resolve().parent.parent
TOKENIZER = AI_SERVER_DIR / "tokenizer" / "ax40light" / "tokenizer.json"
RECIPE = AI_SERVER_DIR.parent / "deploy" / "models" / "ax40light" / "recipe.env"


def _recipe_with(tmp_path: Path, **overrides: str) -> Path:
    """저장소 모델 설정 파일을 복사해 일부 값만 바꾼다."""
    lines = []
    for line in RECIPE.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip()
        if key in overrides:
            value = overrides.pop(key)
            if value is None:
                continue
            line = f"{key}={value}"
        lines.append(line)
    lines += [f"{key}={value}" for key, value in overrides.items() if value is not None]
    path = tmp_path / "recipe.env"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_repository_tokenizer_matches_recipe_hash():
    counter = load_prompt_token_counter(TOKENIZER, RECIPE)
    # 「안녕하세요」를 공식 채팅 틀로 감싼 입력은 6토큰(EXPECTED_PROMPT_TOKENS), 「안녕하세요」 자체는 1토큰
    assert counter.chat_template_tokens == 5
    assert counter.prompt_limit(12288, 512) == 11771


def test_server_limit_comes_from_settings():
    assert main.PROMPT_TOKEN_LIMIT == main.OLLAMA_NUM_CTX - main.OLLAMA_NUM_PREDICT - main.PROMPT_TOKEN_COUNTER.chat_template_tokens


def test_hash_mismatch_is_rejected(tmp_path):
    recipe = _recipe_with(tmp_path, TOKENIZER_SHA256="0" * 64)
    with pytest.raises(ValueError, match="해시가 모델 설정과 다르다"):
        load_prompt_token_counter(TOKENIZER, recipe)


def test_changed_tokenizer_file_is_rejected(tmp_path):
    changed = tmp_path / "tokenizer.json"
    shutil.copyfile(TOKENIZER, changed)
    with changed.open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(ValueError, match="해시가 모델 설정과 다르다"):
        load_prompt_token_counter(changed, RECIPE)


def test_missing_tokenizer_file_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="토크나이저 파일이 없다"):
        load_prompt_token_counter(tmp_path / "tokenizer.json", RECIPE)


def test_missing_hash_or_recipe_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="TOKENIZER_SHA256가 없다"):
        load_prompt_token_counter(TOKENIZER, _recipe_with(tmp_path, TOKENIZER_SHA256=None))
    with pytest.raises(ValueError, match="모델 설정 파일이 없다"):
        load_prompt_token_counter(TOKENIZER, tmp_path / "missing.env")


def test_server_does_not_start_with_wrong_hash(tmp_path):
    """해시가 다른 모델 설정으로 main을 import하면(서버 시작) 실패한다."""
    recipe = _recipe_with(tmp_path, TOKENIZER_SHA256="f" * 64)
    env = {**os.environ, "AI_MODEL_RECIPE_PATH": str(recipe), "OLLAMA_BASE_URL": "http://127.0.0.1:9"}
    env.pop("CHROMA_HOST", None)
    result = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(AI_SERVER_DIR)!r}); import main"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode != 0
    assert "해시가 모델 설정과 다르다" in result.stderr


def test_nfc_makes_same_looking_hangul_the_same_tokens():
    # 공식 토크나이저와 llama.cpp는 정규화하지 않는다. 낱자 조합(NFD) 「가나대학」은 완성형과 다른 토큰이 되고,
    # 서버가 NFC로 바꾼 뒤에야 같은 토큰이 된다
    composed = "가나대학"
    decomposed = unicodedata.normalize("NFD", composed)
    tokenizer = main.PROMPT_TOKEN_COUNTER.tokenizer
    assert decomposed != composed
    assert tokenizer.encode(decomposed, add_special_tokens=False).ids != tokenizer.encode(composed, add_special_tokens=False).ids
    assert tokenizer.encode(nfc(decomposed), add_special_tokens=False).ids == tokenizer.encode(composed, add_special_tokens=False).ids
    assert prompt_tokens.CHAT_TEMPLATE_PROBE == "안녕하세요"


def test_digits_are_counted_with_official_rule():
    # 공식 규칙(GPT-2 정규식)은 이어진 숫자를 세 자리까지 묶는다. 숫자를 한 글자씩 자르는 파일이면 20토큰이 된다
    text = "가나대학 2027학년도 수시1차 모집 인원은 1,250명이다"
    counter = main.PROMPT_TOKEN_COUNTER
    tokens = counter.tokenizer.encode(text, add_special_tokens=False).tokens
    assert "202" in tokens and "250" in tokens
    assert counter.count(text) == 16
