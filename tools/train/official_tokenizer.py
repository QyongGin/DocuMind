"""학습 토크나이저를 원본 폴더의 공식 tokenizer.json 규칙 그대로 부르고, 학습 전에 그 규칙을 확인한다(이슈 #280).

AutoTokenizer는 Transformers 5.8.0부터 config.json의 model_type(A.X 4.0 Light는 qwen2)을 보고 모델 종류별 클래스
(Qwen2Tokenizer)를 고른다. 그 클래스는 tokenizer.json에서 어휘와 병합만 가져오고 정규화(NFC)와 숫자 한 글자 분리를 자기
코드로 붙여, 공식 파일과 서빙(Ollama)이 「110」을 한 토큰으로 볼 때 학습은 세 토큰으로 본다. TokenizersBackend는
tokenizer.json을 그대로 쓴다(tokenization_utils_tokenizers.py의 convert_to_native_format: `cls is TokenizersBackend`면
파일을 고치지 않고 넘긴다). 판이 바뀌어 이 동작이 달라져도 학습 전 확인이 공식 파일로 센 값과 견줘 멈춘다.
"""
from __future__ import annotations

import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

# 서빙(Ollama)의 끝 토큰과 같아야 학습한 답이 같은 자리에서 끝난다(deploy/models/ax40light/Modelfile.tmpl의 stop)
EOS_TOKEN = "<|im_end|>"
# 시스템 글 없이 "안녕하세요"를 공식 채팅 틀로 감싼 입력 토큰 수. Ollama 등록 때 확인하는 값과 같다(recipe.env)
EXPECTED_HELLO_TOKENS = 6
# 공식 규칙과 견줄 글. 숫자 줄(학년도, 금액, 전화번호, 표 칸)과 정규화 전 한글(NFD로 쓴 「학」)을 넣는다.
# 학습 데이터의 답 대부분에 숫자가 있어 숫자를 자르는 규칙이 다르면 답 토큰이 달라진다
RULE_PROBES = (
    "가나대학 2026학년도 1학기 등록금은 1,234,500원이고 110번 강의실, 문의 02-123-4567",
    "| 구분 | 2025 | 2026 |\n| 정원 | 50 | 13 |",
    "학기 시작일은 3월 2일",
)
DIGIT_RUN = re.compile(r"\d{2,}")


def input_ids_of(encoded) -> list[int]:
    """apply_chat_template(tokenize=True) 결과에서 토큰 번호만 꺼낸다.

    Transformers 5는 dict가 아닌 BatchEncoding(Mapping)을 돌려준다. dict로 가르면 키 개수를 토큰 수로 센다.
    """
    return list(encoded["input_ids"] if isinstance(encoded, Mapping) else encoded)


def official_tokenizer(model_dir: str | Path):
    """원본 폴더의 tokenizer.json을 tokenizers 라이브러리로 그대로 읽은 것. 기대 값을 세는 기준이다."""
    from tokenizers import Tokenizer
    return Tokenizer.from_file(str(Path(model_dir).expanduser() / "tokenizer.json"))


def load_tokenizer(model_dir: str | Path):
    """학습에 쓰는 토크나이저. 공식 tokenizer.json 규칙 그대로 부르고, 채팅 틀과 자르는 규칙, 저장할 파일을 확인한다.

    확인에 하나라도 실패하면 학습을 시작하지 않는다(SystemExit).
    """
    from transformers import TokenizersBackend
    tokenizer = TokenizersBackend.from_pretrained(str(Path(model_dir).expanduser()))
    official = official_tokenizer(model_dir)
    check_chat_template(tokenizer, official)
    check_saved_rules(tokenizer, official)
    return tokenizer


def _tokens(tokenizer, text: str) -> list[str]:
    return tokenizer.convert_ids_to_tokens(tokenizer.encode(text, add_special_tokens=False))


def rule_differences(tokenizer, official, text: str) -> list[str]:
    """text를 tokenizer가 공식 파일과 다르게 자르는 곳. 같으면 빈 목록.

    두 자리 이상 숫자마다 따로 견줘 어느 숫자가 어떻게 갈렸는지 적고, 숫자마다 한 글자씩 잘렸으면 그렇다고 적는다.
    숫자가 아닌 곳만 다르면 글 전체의 토큰 수를 적는다.
    """
    if tokenizer.encode(text, add_special_tokens=False) == official.encode(text, add_special_tokens=False).ids:
        return []
    differences = []
    split_runs = []
    for run in dict.fromkeys(DIGIT_RUN.findall(text)):
        ours, theirs = _tokens(tokenizer, run), official.encode(run, add_special_tokens=False).tokens
        if ours != theirs:
            differences.append(f"'{run}' 학습 {ours} / 공식 {theirs}")
            split_runs.append(len(ours) == len(run))
    if split_runs and all(split_runs):
        differences.append("숫자를 한 글자씩 자르는 규칙이 붙었다(모델 종류별 토크나이저 클래스가 불렸는지 본다)")
    if not differences:
        ours = len(tokenizer.encode(text, add_special_tokens=False))
        theirs = len(official.encode(text, add_special_tokens=False).ids)
        differences.append(f"{text!r} 학습 {ours}토큰 / 공식 {theirs}토큰(정규화나 사전 분리 규칙이 다르다)")
    return differences


def check_chat_template(tokenizer, official) -> None:
    """학습에 쓰는 채팅 틀이 서빙(Ollama) 틀과 같은 입력을 만드는지, 끝 토큰이 한 토큰인지, 숫자가 든 글을 공식
    tokenizer.json과 같게 자르는지 확인한다. official은 공식 파일을 그대로 읽은 tokenizers.Tokenizer다."""
    hello_ids = input_ids_of(tokenizer.apply_chat_template([{"role": "user", "content": "안녕하세요"}],
                                                           add_generation_prompt=True, tokenize=True))
    if len(hello_ids) != EXPECTED_HELLO_TOKENS:
        raise SystemExit(f"채팅 틀 확인 실패: '안녕하세요'가 {len(hello_ids)}토큰(서빙 틀은 {EXPECTED_HELLO_TOKENS}토큰)")
    if len(tokenizer.encode(EOS_TOKEN, add_special_tokens=False)) != 1:
        raise SystemExit(f"끝 토큰 {EOS_TOKEN}이 한 토큰이 아니다")
    for text in RULE_PROBES:
        messages = [{"role": "user", "content": text}, {"role": "assistant", "content": text}]
        ours = input_ids_of(tokenizer.apply_chat_template(messages, tokenize=True))
        expected = official.encode(tokenizer.apply_chat_template(messages, tokenize=False), add_special_tokens=False).ids
        if ours != expected:
            details = "; ".join(rule_differences(tokenizer, official, text))
            raise SystemExit(f"자르는 규칙 확인 실패: 채팅 틀을 씌운 글이 학습 {len(ours)}토큰, 공식 tokenizer.json "
                             f"{len(expected)}토큰. {details}")


def check_saved_rules(tokenizer, official) -> None:
    """학습 결과(어댑터 폴더)에 함께 저장될 tokenizer.json이 공식 파일과 같게 자르는지 확인한다."""
    from tokenizers import Tokenizer
    with tempfile.TemporaryDirectory() as folder:
        tokenizer.save_pretrained(folder)
        saved = Tokenizer.from_file(str(Path(folder) / "tokenizer.json"))
    for text in RULE_PROBES:
        if saved.encode(text, add_special_tokens=False).ids != official.encode(text, add_special_tokens=False).ids:
            raise SystemExit(f"저장할 tokenizer.json이 공식 파일과 다르게 자른다: {text!r}")
