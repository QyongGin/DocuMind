"""학습한 LoRA 어댑터를 bf16 원본에 합쳐 Hugging Face 형식으로 저장한다(이슈 #223).

합친 폴더는 deploy/models/convert.sh(SOURCE_DIR)로 4비트 GGUF로 바꾼다. 합치기는 GPU(24GB)에서 한다.
학습 서버 RAM 16GB로는 bf16 7B(약 15GB)를 올리기 빠듯하다. 원본의 LICENSE(Qwen 2.5 고지 포함)를 함께 둔다.

사용 예(학습 서버, 저장소의 tools/train에서):
  python merge_adapter.py --model ~/models/ax40light --adapter ~/runs/r1/adapter --out ~/merged/ax40light-r1
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="원본 모델 폴더(학습에 쓴 것과 같은 판)")
    parser.add_argument("--adapter", required=True, help="train_qlora.py가 남긴 adapter 폴더")
    parser.add_argument("--out", required=True, help="합친 모델을 둘 폴더(비어 있어야 한다)")
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    out = Path(args.out).expanduser()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out}가 비어 있지 않다 — 다른 폴더를 주거나 비운다")
    base = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.bfloat16, device_map="cuda")
    merged = PeftModel.from_pretrained(base, args.adapter).merge_and_unload()
    merged.save_pretrained(out, safe_serialization=True, max_shard_size="4GB")
    AutoTokenizer.from_pretrained(args.model).save_pretrained(out)
    for name in ("LICENSE", "NOTICE"):
        source = Path(args.model).expanduser() / name
        if source.exists():
            shutil.copy(source, out / name)
    print(f"합침: {out}")


if __name__ == "__main__":
    main()
