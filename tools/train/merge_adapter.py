"""학습한 LoRA 어댑터를 bf16 원본에 합쳐 Hugging Face 형식으로 저장한다(이슈 #223).

합친 폴더는 deploy/models/convert.sh(SOURCE_DIR)로 4비트 GGUF로 바꾼다. 합치기는 GPU(24GB)에서 한다.
학습 서버 RAM 16GB로는 bf16 7B(약 15GB)를 올리기 빠듯하다.
가중치 밖의 파일(설정, 토크나이저, LICENSE)은 원본 파일을 그대로 둔다. 학습은 이것들을 바꾸지 않고, Transformers 5로 다시
저장하면 형식이 바뀌어 변환 도구(llama.cpp 이미지의 Transformers 4.57)가 토크나이저를 읽지 못하거나 RoPE 값(rope_theta)을 놓친다.

사용 예(학습 서버, 저장소의 tools/train에서):
  python merge_adapter.py --model ~/models/ax40light --adapter ~/runs/r1/adapter --out ~/merged/ax40light-r1
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

# 원본에서 그대로 가져올 파일. 합친 폴더가 원본과 가중치만 달라야 운영 모델과 같은 길로 변환된다(LICENSE에 Qwen 2.5 고지)
ORIGINAL_FILES = ("config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json", "vocab.json",
                  "merges.txt", "special_tokens_map.json", "LICENSE", "NOTICE")


def weight_names(folder: Path) -> set[str]:
    """safetensors 가중치 이름들. 여러 파일이면 색인에서, 한 파일이면 파일 머리에서 읽는다."""
    index = folder / "model.safetensors.index.json"
    if index.exists():
        return set(json.loads(index.read_text(encoding="utf-8"))["weight_map"])
    from safetensors import safe_open
    with safe_open(str(folder / "model.safetensors"), framework="pt") as weights:
        return set(weights.keys())


def restore_original_files(model_dir: Path, out: Path) -> None:
    """합친 폴더의 가중치 밖 파일을 원본 파일로 바꾼다. 가중치 이름이 원본과 다르면 원본 설정을 쓸 수 없어 멈춘다."""
    if weight_names(model_dir) != weight_names(out):
        raise SystemExit("합친 가중치 이름이 원본과 다르다 — 원본 설정 파일을 그대로 쓸 수 없다")
    for name in ORIGINAL_FILES:
        if (model_dir / name).exists():
            shutil.copy(model_dir / name, out / name)
    # Transformers 5가 따로 쓰는 채팅 틀 파일. 원본은 같은 틀을 tokenizer_config.json 안에 둔다
    (out / "chat_template.jinja").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="원본 모델 폴더(학습에 쓴 것과 같은 판)")
    parser.add_argument("--adapter", required=True, help="train_qlora.py가 남긴 adapter 폴더")
    parser.add_argument("--out", required=True, help="합친 모델을 둘 폴더(비어 있어야 한다)")
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    out = Path(args.out).expanduser()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out}가 비어 있지 않다 — 다른 폴더를 주거나 비운다")
    base = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.bfloat16, device_map="cuda")
    merged = PeftModel.from_pretrained(base, args.adapter).merge_and_unload()
    merged.save_pretrained(out, safe_serialization=True, max_shard_size="4GB")
    restore_original_files(Path(args.model).expanduser(), out)
    print(f"합침: {out}")


if __name__ == "__main__":
    main()
