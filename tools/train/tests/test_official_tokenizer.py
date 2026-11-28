"""학습 토크나이저를 공식 tokenizer.json 규칙 그대로 부르고 확인하기(이슈 #280).

모델을 내려받지 않고, 가나대학 글로 학습한 작은 바이트 BPE 토크나이저로 원본과 같은 모양의 폴더(config.json의
model_type은 qwen2, tokenizer_config.json의 클래스는 GPT2Tokenizer)를 만들어 시험한다. Transformers와 tokenizers만 쓴다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from tokenizers import Regex, Tokenizer, decoders, models, pre_tokenizers, processors, trainers

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from official_tokenizer import (  # noqa: E402
    EOS_TOKEN,
    RULE_PROBES,
    check_chat_template,
    check_saved_rules,
    load_tokenizer,
    official_tokenizer,
    rule_differences,
)

SPECIAL_TOKENS = ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<|user|>", "<|assistant|>", "<|system|>"]
# 원본 틀과 같은 모양: <|im_start|><|역할|>내용<|im_end|>, 답 자리는 <|im_start|><|assistant|>
CHAT_TEMPLATE = ("{%- for message in messages %}{{- '<|im_start|><|' + message.role + '|>' + message.content + '<|im_end|>' }}"
                 "{%- endfor %}{%- if add_generation_prompt %}{{- '<|im_start|><|assistant|>' }}{%- endif %}")
CORPUS = [
    "안녕하세요 가나대학입니다",
    "가나대학 2026학년도 1학기 등록금은 1,234,500원입니다",
    "110번 강의실에서 3월 2일에 개강합니다",
    "문의 02-123-4567 학사지원팀",
    "| 구분 | 2025 | 2026 |",
    "| 정원 | 50 | 13 |",
]


def write_model_folder(folder: Path) -> Path:
    """원본과 같은 규칙(정규화 없음, GPT-2식 바이트 사전 분리: 숫자는 이어진 만큼 한 조각)의 tokenizer.json을 둔다."""
    tokenizer = Tokenizer(models.BPE())
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=True)
    tokenizer.decoder = decoders.ByteLevel()
    tokenizer.post_processor = processors.ByteLevel(trim_offsets=False)
    trainer = trainers.BpeTrainer(vocab_size=700, special_tokens=SPECIAL_TOKENS, show_progress=False,
                                  initial_alphabet=pre_tokenizers.ByteLevel.alphabet())
    tokenizer.train_from_iterator(CORPUS * 50, trainer=trainer)
    folder.mkdir()
    tokenizer.save(str(folder / "tokenizer.json"))
    (folder / "tokenizer_config.json").write_text(json.dumps({
        "tokenizer_class": "GPT2Tokenizer", "add_prefix_space": False, "bos_token": "<|endoftext|>",
        "eos_token": EOS_TOKEN, "pad_token": "<|endoftext|>", "unk_token": "<|endoftext|>",
        "model_max_length": 4096, "chat_template": CHAT_TEMPLATE,
    }, ensure_ascii=False), encoding="utf-8")
    (folder / "config.json").write_text(json.dumps({
        "model_type": "qwen2", "architectures": ["Qwen2ForCausalLM"], "transformers_version": "4.51.3",
        "vocab_size": tokenizer.get_vocab_size(),
    }), encoding="utf-8")
    return folder


def write_digit_split_copy(model_dir: Path, folder: Path) -> Path:
    """같은 어휘와 병합에 숫자 한 글자 분리를 붙인 폴더(Transformers 5.8.0부터 AutoTokenizer가 고르는 규칙과 같은 모양)."""
    tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
    tokenizer.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(Regex(r"\p{N}"), behavior="isolated"),
        pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=True),
    ])
    folder.mkdir()
    tokenizer.save(str(folder / "tokenizer.json"))
    for name in ("tokenizer_config.json", "config.json"):
        (folder / name).write_text((model_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
    return folder


@pytest.fixture(scope="module")
def model_dir(tmp_path_factory) -> Path:
    return write_model_folder(tmp_path_factory.mktemp("gana") / "model")


@pytest.fixture(scope="module")
def digit_split(model_dir, tmp_path_factory):
    from transformers import TokenizersBackend
    return TokenizersBackend.from_pretrained(str(write_digit_split_copy(model_dir, tmp_path_factory.mktemp("split") / "model")))


def test_fixture_cuts_numbers_into_multi_digit_tokens(model_dir):
    # 시험이 뜻이 있으려면 공식 규칙에서 숫자가 여러 글자 토큰으로 묶여야 한다
    assert official_tokenizer(model_dir).encode("110", add_special_tokens=False).tokens == ["110"]


def test_load_tokenizer_keeps_official_rules_on_qwen2_folder(model_dir):
    tokenizer = load_tokenizer(model_dir)  # 확인을 모두 통과해야 돌아온다
    official = official_tokenizer(model_dir)

    for text in RULE_PROBES + ("110", "02-123-4567"):
        assert tokenizer.encode(text, add_special_tokens=False) == official.encode(text, add_special_tokens=False).ids
    assert len(tokenizer.encode(EOS_TOKEN, add_special_tokens=False)) == 1


def test_saved_tokenizer_cuts_like_official_file(model_dir, tmp_path):
    # 학습이 어댑터 폴더에 함께 저장하는 tokenizer.json도 공식 규칙이어야 한다
    load_tokenizer(model_dir).save_pretrained(str(tmp_path))
    saved, official = Tokenizer.from_file(str(tmp_path / "tokenizer.json")), official_tokenizer(model_dir)

    for text in RULE_PROBES:
        assert saved.encode(text, add_special_tokens=False).ids == official.encode(text, add_special_tokens=False).ids


def test_check_stops_when_numbers_are_cut_one_digit_at_a_time(model_dir, digit_split):
    with pytest.raises(SystemExit) as stopped:
        check_chat_template(digit_split, official_tokenizer(model_dir))

    message = str(stopped.value)
    assert "자르는 규칙 확인 실패" in message
    assert "'110' 학습 ['1', '1', '0'] / 공식 ['110']" in message
    assert "한 글자씩" in message


def test_check_saved_rules_stops_on_digit_split_file(model_dir, digit_split):
    with pytest.raises(SystemExit, match="저장할 tokenizer.json"):
        check_saved_rules(digit_split, official_tokenizer(model_dir))


def test_rule_differences_is_empty_for_official_rules(model_dir):
    tokenizer = load_tokenizer(model_dir)

    assert all(rule_differences(tokenizer, official_tokenizer(model_dir), text) == [] for text in RULE_PROBES)


def test_check_still_stops_on_wrong_chat_template(model_dir):
    tokenizer = load_tokenizer(model_dir)
    tokenizer.chat_template = "{%- for message in messages %}{{- '<|im_start|>' + message.content }}{%- endfor %}"

    with pytest.raises(SystemExit, match="채팅 틀 확인 실패"):
        check_chat_template(tokenizer, official_tokenizer(model_dir))
