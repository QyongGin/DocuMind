"""A.X 4.0 Light 4회차 선호 학습(DPO, ADR-0053, 이슈 #225). 학습 서버(AWS g5.xlarge, A10G 24GB)에서 돌린다.

3회차 지도 학습 어댑터를 불러 이어 학습한다. 기준 모델은 학습을 시작할 때의 3회차 모델이다: 이어 학습하는 PeftModel을 주면
TRL이 그 어댑터를 "ref"라는 이름으로 복사해 고정하고 기준 확률을 그 어댑터로 잰다. 손실은 DPO(sigmoid)에 선호 답의 토큰당
음의 로그 가능도(sft)를 같은 가중치로 더한다. 원본은 4비트(NF4)로 올리고, 반복마다 검증 몫 손실을 재 가장 낮은 반복의 어댑터를
남긴다. 결과 폴더에 어댑터와 실행 기록(run_manifest.json: 설정, 데이터·시작 어댑터 SHA256, 라이브러리 판, 걸린 시간,
최대 GPU 메모리, 가장 좋은 반복의 검증 지표)을 둔다. 학습 중 드롭아웃은 TRL 기본값(disable_dropout)대로 끈다.

사용 예(학습 서버, 저장소의 tools/train에서):
  python train_dpo.py --model ~/models/ax40light --adapter ~/runs/r3/adapter --data ~/data/pairs.jsonl --out ~/runs/r4
  한 바퀴 시험: --limit 20 --max-steps 10
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from data import load_pairs, split_examples, to_preference
from train_qlora import check_chat_template, input_ids_of, sha256_of

# 설계 §4: DPO에 선호 답 가능도를 더한다. 비선호 답만 눌러 다른 틀린 답이 느는 것을 막는다
LOSS_TYPES = ["sigmoid", "sft"]
LOSS_WEIGHTS = [1.0, 1.0]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="원본 모델 폴더(3회차를 학습한 것과 같은 판, skt/A.X-4.0-Light)")
    parser.add_argument("--adapter", required=True, help="이어 학습할 어댑터 폴더(3회차 train_qlora.py 결과의 adapter)")
    parser.add_argument("--data", required=True, help="선호 쌍 파일(JSONL, trainset pairs 결과)")
    parser.add_argument("--out", required=True, help="결과 폴더")
    parser.add_argument("--valid-ratio", type=float, default=0.1, help="검증 몫 비율(쌍 종류 비율대로 고른다)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-length", type=int, default=8192, help="프롬프트와 답이 이보다 긴 쌍이 있으면 자르지 않고 멈춘다")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=1e-5, help="TRL 문서의 어댑터 학습 권장값")
    parser.add_argument("--beta", type=float, default=0.1, help="기준 모델에서 벗어나는 정도를 누르는 값(TRL 기본값)")
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="학습 몫을 앞에서 이만큼만 쓴다(한 바퀴 시험)")
    parser.add_argument("--max-steps", type=int, default=-1, help="한 바퀴 시험: 이 걸음만 학습하고 반복별 검증은 하지 않는다")
    return parser.parse_args(argv)


def valid_count(total: int, ratio: float) -> int:
    """검증 몫 개수. 비율이 0보다 크면 적어도 1개."""
    return max(1, round(total * ratio)) if ratio > 0 else 0


def pair_lengths(tokenizer, pairs: list[dict]) -> list[int]:
    """쌍마다 채팅 틀을 씌운 프롬프트와 답의 토큰 수 중 긴 쪽(끝 토큰 포함). TRL이 선호 답과 비선호 답을 따로 이어 붙여
    max_length로 자르므로 둘 다 그 안이어야 한다."""
    return [max(len(input_ids_of(tokenizer.apply_chat_template(pair["prompt"] + pair[answer], tokenize=True)))
                for answer in ("chosen", "rejected"))
            for pair in pairs]


def best_eval(log_history: list[dict]) -> dict:
    """검증 손실이 가장 낮은 반복의 검증 지표(eval_loss, eval_rewards/accuracies 등). 검증하지 않았으면 빈 사전."""
    evals = [entry for entry in log_history if "eval_loss" in entry]
    if not evals:
        return {}
    best = min(evals, key=lambda entry: entry["eval_loss"])
    return {key: value for key, value in best.items() if key.startswith("eval_") or key == "epoch"}


def main() -> None:
    args = parse_args()
    import torch
    from datasets import Dataset
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import DPOConfig, DPOTrainer

    started = time.time()
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    adapter = Path(args.adapter).expanduser()
    if (out / "adapter").resolve() == adapter.resolve():
        raise SystemExit(f"결과 어댑터 자리({out / 'adapter'})가 시작 어댑터와 같다 — 3회차 어댑터를 덮어쓰지 않게 다른 --out을 준다")
    start_adapter_sha256 = sha256_of(adapter / "adapter_model.safetensors")
    pairs = load_pairs(args.data)
    train, valid = split_examples(pairs, valid_size=valid_count(len(pairs), args.valid_ratio), seed=args.seed, key="pair")
    if args.limit:
        train = train[:args.limit]

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    check_chat_template(tokenizer)
    lengths = pair_lengths(tokenizer, train + valid)
    too_long = [pair["id"] for pair, length in zip(train + valid, lengths) if length > args.max_length]
    if too_long:
        raise SystemExit(f"{len(too_long)}개 쌍이 {args.max_length}토큰보다 길다(TRL은 뒤를 잘라 답이 잘린다): {too_long[:5]}")
    print(f"학습 {len(train)}쌍, 검증 {len(valid)}쌍, 토큰 최대 {max(lengths)}, 중앙 {sorted(lengths)[len(lengths) // 2]}")

    smoke = args.max_steps > 0
    steps_per_epoch = math.ceil(len(train) / args.grad_accum)
    total_steps = args.max_steps if smoke else math.ceil(steps_per_epoch * args.epochs)
    config = DPOConfig(
        output_dir=str(out / "checkpoints"),
        max_length=args.max_length,
        beta=args.beta,
        loss_type=LOSS_TYPES,
        loss_weights=LOSS_WEIGHTS,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_steps=max(1, round(total_steps * 0.05)),
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.grad_accum,
        gradient_checkpointing=True,
        bf16=True,
        logging_steps=1 if smoke else 5,
        eval_strategy="no" if smoke else "epoch",
        save_strategy="no" if smoke else "epoch",
        load_best_model_at_end=not smoke,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        save_total_limit=None if smoke else math.ceil(args.epochs),
        seed=args.seed,
        report_to="none",
    )
    # 1~3회차와 같은 4비트 설정으로 원본을 올리고 3회차 어댑터를 학습할 수 있게 붙인다. LoRA 설정(r·α·층)은 어댑터의 것을 쓴다
    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                      bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    base = AutoModelForCausalLM.from_pretrained(args.model, quantization_config=quantization, dtype=torch.bfloat16,
                                                device_map="auto")
    model = PeftModel.from_pretrained(base, str(adapter), is_trainable=True)
    trainer = DPOTrainer(
        model=model,
        args=config,
        train_dataset=Dataset.from_list([to_preference(pair) for pair in train]),
        eval_dataset=None if smoke else Dataset.from_list([to_preference(pair) for pair in valid]),
        processing_class=tokenizer,
    )
    torch.cuda.reset_peak_memory_stats()
    train_started = time.time()
    trainer.train()
    train_seconds = time.time() - train_started
    # 기준 모델로 쓴 "ref" 어댑터는 빼고 학습한 어댑터만 merge_adapter.py가 읽는 자리에 둔다
    trainer.model.save_pretrained(str(out / "adapter"), selected_adapters=["default"])

    manifest = {
        "args": vars(args),
        "loss": {"types": LOSS_TYPES, "weights": LOSS_WEIGHTS, "disable_dropout": config.disable_dropout},
        "data_sha256": sha256_of(args.data),
        "start_adapter_sha256": start_adapter_sha256,
        "train_ids": [pair["id"] for pair in train],
        "valid_ids": [pair["id"] for pair in valid],
        "token_lengths": {"max": max(lengths), "median": sorted(lengths)[len(lengths) // 2]},
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "best_eval": best_eval(trainer.state.log_history),
        "log_history": trainer.state.log_history,
        "seconds": {"train": round(train_seconds), "total": round(time.time() - started)},
        "peak_gpu_memory_gib": round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2),
        "gpu": torch.cuda.get_device_name(0),
        "python": sys.version.split()[0],
        "pip_freeze": subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout.split(),
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    best = manifest["best_eval"]
    print(f"끝: 어댑터 {out / 'adapter'}, 학습 {manifest['seconds']['train']}초, 최대 GPU 메모리 {manifest['peak_gpu_memory_gib']}GiB, "
          f"검증 손실 {best.get('eval_loss')}, 선호 답 보상이 큰 쌍 비율 {best.get('eval_rewards/accuracies')}")


if __name__ == "__main__":
    main()
