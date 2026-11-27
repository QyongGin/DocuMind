#!/usr/bin/env bash
# 공식 원본(Hugging Face, 커밋 고정)을 Ollama에 올릴 4비트 GGUF로 바꾼다(ADR-0036).
#
# 사용법(데스크탑 WSL, 저장소 루트에서): deploy/models/convert.sh deploy/models/ax40light
# 학습한 모델(학습 서버에서 합친 Hugging Face 폴더)은 SOURCE_DIR로 그 폴더를 주면 내려받지 않고 그 폴더를 바꾼다:
#   SOURCE_DIR=~/merged/ax40light-r1 deploy/models/convert.sh deploy/models/ax40light-r1
# 결과: Docker 볼륨 model_work 안 <NAME>/ 폴더에 <NAME>-<QUANT>.gguf, 원본 LICENSE·config.json·tokenizer_config.json,
#       SHA256SUMS, LLAMA_CPP_VERSION(PRE_TOKENIZER가 있으면 PRE_TOKENIZER_CHECK.json도). 원본(약 14.5GB)과 16비트 GGUF(약 13.8GB),
#       분리 규칙을 바꾸기 전 4비트 GGUF는 다음 단계가 끝나면 지운다.
# 시간: 원본 내려받기 포함 약 8분(RTX 4070 Super 데스크탑, 2026-10-01).
#
# recipe.env에 PRE_TOKENIZER가 있으면 양자화한 GGUF의 토크나이저 분리 규칙 이름(tokenizer.ggml.pre)을 그 값으로 바꾼다(이슈 #279).
# llama.cpp는 변환 때 A.X 4.0에 붙는 이름 a.x-4.0을 숫자 줄을 한 덩어리로 자르는 GPT-2 규칙에 묶어,
# 숫자를 한 글자씩 자르는 공식 tokenizer.json과 토큰이 달라진다. 텐서는 그대로이고, 바꾼 뒤 메타데이터 한 칸만 달라졌는지 확인한다.
# 값이 없는 레시피는 바꾸지 않는다(그전에 만든 파일과 같은 SHA256).
#
# 환경값: MODEL_VOLUME(기본 model_work, 절대 경로면 그 폴더), LLAMA_CPP_IMAGE(기본은 아래 고정 판), SOURCE_DIR(내려받는 대신 바꿀 로컬 폴더)
set -euo pipefail

dir=${1:?"모델 폴더를 준다. 예: deploy/models/ax40light"}
# shellcheck source=/dev/null
source "$dir/recipe.env"
: "${NAME:?recipe.env에 NAME이 없다}" "${QUANT:?recipe.env에 QUANT가 없다}"
SOURCE_DIR=${SOURCE_DIR:-}
if [ -z "$SOURCE_DIR" ]; then
  : "${HF_REPO:?recipe.env에 HF_REPO가 없다(학습한 모델이면 SOURCE_DIR를 준다)}" "${HF_REVISION:?recipe.env에 HF_REVISION이 없다}"
elif [ ! -f "$SOURCE_DIR/config.json" ]; then
  echo "SOURCE_DIR에 config.json이 없다: $SOURCE_DIR" >&2
  exit 1
fi

# 변환 도구 판을 고정한다: 같은 원본·같은 도구면 같은 파일(같은 SHA256)이 나온다.
# build 11312(커밋 0c1e57098), 2026-10-01 A.X 변환에 쓴 이미지와 같은 지문.
LLAMA_CPP_IMAGE=${LLAMA_CPP_IMAGE:-ghcr.io/ggml-org/llama.cpp:full-b11312@sha256:f9c7815efe7ac3fddfc4d162f8b353f01752dc61896681810f3a5c430b96c3de}
VOLUME=${MODEL_VOLUME:-model_work}
gguf="$NAME-$QUANT.gguf"

# MODEL_VOLUME가 절대 경로면 그 폴더를 그대로 쓴다(학습 서버에서 결과 파일을 바로 옮길 때)
case "$VOLUME" in
  /*) mkdir -p "$VOLUME" ;;
  *) docker volume create "$VOLUME" > /dev/null ;;
esac
if docker run --rm -v "$VOLUME":/work --entrypoint test "$LLAMA_CPP_IMAGE" -e "/work/$NAME/$gguf" < /dev/null; then
  echo "이미 있음: 볼륨 $VOLUME 의 $NAME/$gguf — 다시 만들려면 그 파일을 먼저 옮기거나 다른 MODEL_VOLUME을 쓴다" >&2
  exit 1
fi

source_mount=()
if [ -n "$SOURCE_DIR" ]; then
  source_mount=(-v "$(cd "$SOURCE_DIR" && pwd)":/src:ro -e SOURCE=/src)
fi
docker run --rm -i -v "$VOLUME":/work ${source_mount[@]+"${source_mount[@]}"} \
  -e NAME="$NAME" -e HF_REPO="${HF_REPO:-}" -e HF_REVISION="${HF_REVISION:-}" -e QUANT="$QUANT" \
  -e PRE_TOKENIZER="${PRE_TOKENIZER:-}" \
  --entrypoint bash "$LLAMA_CPP_IMAGE" -s <<'INNER'
set -euo pipefail
out=/work/$NAME
mkdir -p "$out"
if [ -n "${SOURCE:-}" ]; then
  src=$SOURCE
else
  python3 - <<'PY'
import os
from huggingface_hub import snapshot_download

snapshot_download(os.environ["HF_REPO"], revision=os.environ["HF_REVISION"],
                  local_dir=f"/work/{os.environ['NAME']}/hf")
PY
  src=$out/hf
fi
du -sh "$src"
# 넘겨줄 때 함께 둘 원본 파일(LICENSE에 Qwen 2.5 고지가 들어 있다)과 변환 확인용 설정
cp "$src/LICENSE" "$src/config.json" "$src/tokenizer_config.json" "$out/"
# 아래 명령들은 표준 입력을 막는다: 이 스크립트 자체가 표준 입력으로 들어오고 있어, 읽으면 뒤 줄을 먹는다
python3 /app/convert_hf_to_gguf.py "$src" --outtype bf16 --outfile "$out/$NAME-bf16.gguf" < /dev/null
rm -rf "$out/hf"
if [ -z "${PRE_TOKENIZER:-}" ]; then
  /app/llama-quantize "$out/$NAME-bf16.gguf" "$out/$NAME-$QUANT.gguf" "$QUANT" < /dev/null
  rm -f "$out/$NAME-bf16.gguf"
else
  # 양자화한 파일을 중간 파일로 두고, 분리 규칙 이름만 바꾼 사본을 최종 파일로 쓴다. 16비트 GGUF를 먼저 지워 디스크를 더 쓰지 않는다
  orig=$out/$NAME-$QUANT.pre-orig.gguf
  /app/llama-quantize "$out/$NAME-bf16.gguf" "$orig" "$QUANT" < /dev/null
  rm -f "$out/$NAME-bf16.gguf"
  # 바꾸기나 확인이 실패하면 두 파일을 모두 지운다(다시 돌릴 때 「이미 있음」에 걸리지 않고, 4GB 넘는 파일을 남기지 않는다)
  trap 'rm -f "$orig" "$out/$NAME-$QUANT.gguf"' ERR
  export PYTHONPATH=/app/gguf-py${PYTHONPATH:+:$PYTHONPATH}
  python3 /app/gguf-py/gguf/scripts/gguf_new_metadata.py --pre-tokenizer "$PRE_TOKENIZER" "$orig" "$out/$NAME-$QUANT.gguf" < /dev/null
  # 메타데이터는 tokenizer.ggml.pre 한 칸만, 텐서는 이름·모양·자료형·데이터 해시가 모두 같아야 한다
  python3 - "$orig" "$out/$NAME-$QUANT.gguf" > "$out/PRE_TOKENIZER_CHECK.json" <<'PY'
import hashlib, json, os, sys
from gguf import GGUFReader

def fields(reader):
    out = {}
    for key, field in reader.fields.items():
        if key.startswith("GGUF."):
            continue
        try:
            out[key] = field.contents()
        except Exception:
            out[key] = [bytes(part).hex() for part in field.parts]
    return out

a, b = GGUFReader(sys.argv[1]), GGUFReader(sys.argv[2])
fa, fb = fields(a), fields(b)
meta_diff = {k: [fa.get(k), fb.get(k)] for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)}
ta, tb = {t.name: t for t in a.tensors}, {t.name: t for t in b.tensors}
tensor_diff = []
for name in sorted(set(ta) | set(tb)):
    x, y = ta.get(name), tb.get(name)
    if x is None or y is None:
        tensor_diff.append([name, "missing"])
    elif list(x.shape) != list(y.shape) or x.tensor_type != y.tensor_type:
        tensor_diff.append([name, "shape/type"])
    elif hashlib.sha256(x.data.tobytes()).digest() != hashlib.sha256(y.data.tobytes()).digest():
        tensor_diff.append([name, "data"])
result = {"meta_keys": len(fa), "meta_diff": meta_diff, "tensors": len(ta), "tensor_diff": tensor_diff}
print(json.dumps(result, ensure_ascii=False, default=str))
want = os.environ["PRE_TOKENIZER"]
ok = (not tensor_diff and set(meta_diff) <= {"tokenizer.ggml.pre"} and fb.get("tokenizer.ggml.pre") == want)
if not ok:
    print(f"분리 규칙 바꾸기 확인 실패: {json.dumps(result, ensure_ascii=False, default=str)}", file=sys.stderr)
    sys.exit(1)
print(f"분리 규칙 {fa.get('tokenizer.ggml.pre')} → {want}, 텐서 {len(ta)}개 같음", file=sys.stderr)
PY
  trap - ERR
  rm -f "$orig"
fi
{ /app/llama-cli --version 2>&1 < /dev/null || true; } | grep -E "^(version|built with)" > "$out/LLAMA_CPP_VERSION" || true
cd "$out" && sha256sum "$NAME-$QUANT.gguf" > SHA256SUMS
ls -la "$out"
INNER

actual=$(docker run --rm -v "$VOLUME":/work --entrypoint cat "$LLAMA_CPP_IMAGE" "/work/$NAME/SHA256SUMS" < /dev/null | cut -d' ' -f1)
echo "SHA256 $actual  $gguf"
if [ -n "${EXPECTED_SHA256:-}" ]; then
  if [ "$actual" = "$EXPECTED_SHA256" ]; then
    echo "모델 대장의 SHA256과 같다"
  else
    echo "모델 대장의 SHA256($EXPECTED_SHA256)과 다르다 — 원본 커밋·변환 도구 판을 확인한다" >&2
    exit 1
  fi
fi
