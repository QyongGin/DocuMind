"""A.X 4.0 Light QLoRA 학습(ADR-0033, 이슈 #223). 학습 서버(AWS g5.xlarge, A10G 24GB)에서 돌린다.

학습 예시를 대화형 프롬프트·답 형식으로 바꿔 답 부분만 학습한다. 원본은 4비트(NF4)로 올리고 LoRA 어댑터만 학습하며,
회차(epoch)마다 검증 몫 손실을 재 가장 낮은 회차의 어댑터를 남긴다. 결과 폴더에 어댑터, 학습 기록, 실행 기록
(run_manifest.json: 설정, 데이터 SHA256, 라이브러리 판, 걸린 시간, 최대 GPU 메모리)을 둔다.

사용 예(학습 서버, 저장소의 tools/train에서):
  python train_qlora.py --model ~/models/ax40light --data ~/data/round-ga.jsonl --out ~/runs/r1
  한 바퀴 시험: --limit 20 --max-steps 10
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from data import load_examples, split_examples, to_prompt_completion

# 서빙(Ollama)의 끝 토큰과 같아야 학습한 답이 같은 자리에서 끝난다(deploy/models/ax40light/Modelfile.tmpl의 stop)
EOS_TOKEN = "<|im_end|>"
# 시스템 글 없이 "안녕하세요"를 공식 채팅 틀로 감싼 입력 토큰 수. Ollama 등록 때 확인하는 값과 같다(recipe.env)
EXPECTED_HELLO_TOKENS = 6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="원본 모델 폴더(Hugging Face 형식, skt/A.X-4.0-Light)")
    parser.add_argument("--data", required=True, help="학습 파일(JSONL, export-round 결과)")
    parser.add_argument("--out", required=True, help="결과 폴더")
    parser.add_argument("--valid-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-length", type=int, default=8192, help="이보다 긴 예시가 있으면 자르지 않고 멈춘다")
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--limit", type=int, default=0, help="학습 몫을 앞에서 이만큼만 쓴다(한 바퀴 시험)")
    parser.add_argument("--max-steps", type=int, default=-1, help="한 바퀴 시험: 이 걸음만 학습하고 회차별 검증은 하지 않는다")
    return parser.parse_args()


def sha256_of(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_ids_of(encoded) -> list[int]:
    """apply_chat_template(tokenize=True) 결과에서 토큰 번호만 꺼낸다.

    Transformers 5는 dict가 아닌 BatchEncoding(Mapping)을 돌려준다. dict로 가르면 키 개수를 토큰 수로 센다.
    """
    return list(encoded["input_ids"] if isinstance(encoded, Mapping) else encoded)


def check_chat_template(tokenizer) -> None:
    """학습에 쓰는 채팅 틀이 서빙(Ollama) 틀과 같은 입력을 만드는지, 끝 토큰이 한 토큰인지 확인한다."""
    hello_ids = input_ids_of(tokenizer.apply_chat_template([{"role": "user", "content": "안녕하세요"}],
                                                           add_generation_prompt=True, tokenize=True))
    if len(hello_ids) != EXPECTED_HELLO_TOKENS:
        raise SystemExit(f"채팅 틀 확인 실패: '안녕하세요'가 {len(hello_ids)}토큰(서빙 틀은 {EXPECTED_HELLO_TOKENS}토큰)")
    if len(tokenizer.encode(EOS_TOKEN, add_special_tokens=False)) != 1:
        raise SystemExit(f"끝 토큰 {EOS_TOKEN}이 한 토큰이 아니다")


def example_lengths(tokenizer, examples: list[dict]) -> list[int]:
    """채팅 틀을 씌운 프롬프트와 답의 토큰 수(끝 토큰 포함)."""
    lengths = []
    for example in examples:
        lengths.append(len(input_ids_of(tokenizer.apply_chat_template(example["messages"], tokenize=True))))
    return lengths


def main() -> None:
    args = parse_args()
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    started = time.time()
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    examples = load_examples(args.data)
    train, valid = split_examples(examples, valid_size=args.valid_size, seed=args.seed)
    if args.limit:
        train = train[:args.limit]

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    check_chat_template(tokenizer)
    lengths = example_lengths(tokenizer, train + valid)
    too_long = [example["id"] for example, length in zip(train + valid, lengths) if length > args.max_length]
    if too_long:
        raise SystemExit(f"{len(too_long)}개 예시가 {args.max_length}토큰보다 길다(자르면 답이 잘린다): {too_long[:5]}")
    print(f"학습 {len(train)}개, 검증 {len(valid)}개, 토큰 최대 {max(lengths)}, 중앙 {sorted(lengths)[len(lengths) // 2]}")

    smoke = args.max_steps > 0
    steps_per_epoch = math.ceil(len(train) / args.grad_accum)
    total_steps = args.max_steps if smoke else math.ceil(steps_per_epoch * args.epochs)
    config = SFTConfig(
        output_dir=str(out / "checkpoints"),
        max_length=args.max_length,
        eos_token=EOS_TOKEN,
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
        model_init_kwargs={"dtype": torch.bfloat16},
    )
    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                      bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    lora = LoraConfig(r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.05, target_modules="all-linear",
                      task_type="CAUSAL_LM")
    trainer = SFTTrainer(
        model=args.model,
        args=config,
        train_dataset=Dataset.from_list([to_prompt_completion(example) for example in train]),
        eval_dataset=None if smoke else Dataset.from_list([to_prompt_completion(example) for example in valid]),
        processing_class=tokenizer,
        quantization_config=quantization,
        peft_config=lora,
    )
    torch.cuda.reset_peak_memory_stats()
    train_started = time.time()
    trainer.train()
    train_seconds = time.time() - train_started
    trainer.save_model(str(out / "adapter"))

    manifest = {
        "args": vars(args),
        "data_sha256": sha256_of(args.data),
        "train_ids": [example["id"] for example in train],
        "valid_ids": [example["id"] for example in valid],
        "token_lengths": {"max": max(lengths), "median": sorted(lengths)[len(lengths) // 2]},
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "log_history": trainer.state.log_history,
        "seconds": {"train": round(train_seconds), "total": round(time.time() - started)},
        "peak_gpu_memory_gib": round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2),
        "gpu": torch.cuda.get_device_name(0),
        "python": sys.version.split()[0],
        "pip_freeze": subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout.split(),
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"끝: 어댑터 {out / 'adapter'}, 학습 {manifest['seconds']['train']}초, 최대 GPU 메모리 {manifest['peak_gpu_memory_gib']}GiB")


if __name__ == "__main__":
    main()
