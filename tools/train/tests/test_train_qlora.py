"""학습 스크립트의 채팅 틀 토큰 세기(이슈 #223). 학습 라이브러리 없이 돈다."""
from __future__ import annotations

import sys
from collections import UserDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from train_qlora import input_ids_of  # noqa: E402


def test_input_ids_of_counts_tokens_not_keys_of_mapping_result():
    # Transformers 5의 BatchEncoding처럼 dict가 아닌 Mapping이 와도 키 개수가 아니라 토큰 번호를 꺼낸다
    encoded = UserDict({"input_ids": [25, 8, 3218, 27, 25, 10], "attention_mask": [1] * 6})

    assert input_ids_of(encoded) == [25, 8, 3218, 27, 25, 10]


def test_input_ids_of_keeps_plain_token_list():
    assert input_ids_of([25, 8, 3218]) == [25, 8, 3218]
