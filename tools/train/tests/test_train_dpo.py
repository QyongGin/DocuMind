"""선호 학습 스크립트의 쌍 길이 세기·검증 몫 개수·검증 지표 고르기·설정값(이슈 #225). 학습 라이브러리 없이 돈다."""
from __future__ import annotations

import sys
from collections import UserDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from train_dpo import LOSS_TYPES, LOSS_WEIGHTS, best_eval, pair_lengths, parse_args, valid_count  # noqa: E402


class CountingTokenizer:
    """글자 하나를 토큰 하나로 세는 가짜 토크나이저. Transformers 5처럼 Mapping을 돌려준다."""

    def apply_chat_template(self, messages, tokenize=True):
        text = "".join(f"<{message['role']}>{message['content']}<end>" for message in messages)
        return UserDict({"input_ids": list(range(len(text)))})


def pair(chosen: str, rejected: str) -> dict:
    return {"id": "gana-001", "prompt": [{"role": "user", "content": "가나대학 휴학 언제까지?"}],
            "chosen": [{"role": "assistant", "content": chosen}], "rejected": [{"role": "assistant", "content": rejected}]}


def test_pair_length_is_prompt_with_the_longer_answer():
    short, long = "8월 29일까지입니다.", "학교 홈페이지 안내에서 찾지 못했습니다. 학사지원팀에 문의하세요."
    prompt_part = len("<user>가나대학 휴학 언제까지?<end>") + len("<assistant><end>")
    assert pair_lengths(CountingTokenizer(), [pair(short, long)]) == [prompt_part + len(long)]
    assert pair_lengths(CountingTokenizer(), [pair(long, short)]) == [prompt_part + len(long)]  # 긴 답이 어느 쪽이어도


def test_valid_count_is_ratio_with_at_least_one():
    assert valid_count(200, 0.1) == 20 and valid_count(5, 0.1) == 1 and valid_count(200, 0) == 0


def test_best_eval_takes_lowest_validation_loss():
    history = [{"loss": 0.9, "epoch": 0.5},
               {"eval_loss": 0.62, "eval_rewards/accuracies": 0.7, "epoch": 1.0},
               {"eval_loss": 0.55, "eval_rewards/accuracies": 0.8, "eval_rewards/margins": 1.2, "epoch": 2.0},
               {"train_loss": 0.7, "epoch": 2.0}]
    assert best_eval(history) == {"eval_loss": 0.55, "eval_rewards/accuracies": 0.8, "eval_rewards/margins": 1.2, "epoch": 2.0}
    assert best_eval([{"loss": 0.9}]) == {}  # 한 바퀴 시험은 검증하지 않는다


def test_defaults_follow_round4_design():
    # 설계 §4: β 0.1(TRL 기본), 학습률 1e-5(어댑터 권장), 반복 2번, 최대 8,192토큰, 손실 DPO + 선호 답 가능도
    args = parse_args(["--model", "m", "--adapter", "a", "--data", "d", "--out", "o"])
    assert (args.beta, args.learning_rate, args.epochs, args.max_length, args.valid_ratio) == (0.1, 1e-5, 2.0, 8192, 0.1)
    assert LOSS_TYPES == ["sigmoid", "sft"] and LOSS_WEIGHTS == [1.0, 1.0]
