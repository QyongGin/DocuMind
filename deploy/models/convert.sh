#!/usr/bin/env bash
# 공식 원본(Hugging Face, 커밋 고정)을 Ollama에 올릴 4비트 GGUF로 바꾼다(ADR-0036).
#
# 사용법(데스크탑 WSL, 저장소 루트에서): deploy/models/convert.sh deploy/models/ax40light
# 결과: Docker 볼륨 model_work 안 <NAME>/ 폴더에 <NAME>-<QUANT>.gguf, 원본 LICENSE·config.json·tokenizer_config.json,
#       SHA256SUMS, LLAMA_CPP_VERSION. 원본(약 14.5GB)과 16비트 GGUF(약 13.8GB)는 변환 뒤 지운다.
# 시간: 원본 내려받기 포함 약 8분(RTX 4070 Super 데스크탑, 2026-10-01).
#
# 환경값: MODEL_VOLUME(기본 model_work), LLAMA_CPP_IMAGE(기본은 아래 고정 판)
set -euo pipefail

dir=${1:?"모델 폴더를 준다. 예: deploy/models/ax40light"}
# shellcheck source=/dev/null
source "$dir/recipe.env"
: "${NAME:?recipe.env에 NAME이 없다}" "${HF_REPO:?recipe.env에 HF_REPO가 없다}"
: "${HF_REVISION:?recipe.env에 HF_REVISION이 없다}" "${QUANT:?recipe.env에 QUANT가 없다}"

# 변환 도구 판을 고정한다: 같은 원본·같은 도구면 같은 파일(같은 SHA256)이 나온다.
# build 11312(커밋 0c1e57098), 2026-10-01 A.X 변환에 쓴 이미지와 같은 지문.
LLAMA_CPP_IMAGE=${LLAMA_CPP_IMAGE:-ghcr.io/ggml-org/llama.cpp:full-b11312@sha256:f9c7815efe7ac3fddfc4d162f8b353f01752dc61896681810f3a5c430b96c3de}
VOLUME=${MODEL_VOLUME:-model_work}
gguf="$NAME-$QUANT.gguf"

docker volume create "$VOLUME" > /dev/null
if docker run --rm -v "$VOLUME":/work --entrypoint test "$LLAMA_CPP_IMAGE" -e "/work/$NAME/$gguf" < /dev/null; then
  echo "이미 있음: 볼륨 $VOLUME 의 $NAME/$gguf — 다시 만들려면 그 파일을 먼저 옮기거나 다른 MODEL_VOLUME을 쓴다" >&2
  exit 1
fi

docker run --rm -i -v "$VOLUME":/work \
  -e NAME="$NAME" -e HF_REPO="$HF_REPO" -e HF_REVISION="$HF_REVISION" -e QUANT="$QUANT" \
  --entrypoint bash "$LLAMA_CPP_IMAGE" -s <<'INNER'
set -euo pipefail
out=/work/$NAME
mkdir -p "$out"
python3 - <<'PY'
import os
from huggingface_hub import snapshot_download

snapshot_download(os.environ["HF_REPO"], revision=os.environ["HF_REVISION"],
                  local_dir=f"/work/{os.environ['NAME']}/hf")
PY
du -sh "$out/hf"
# 넘겨줄 때 함께 둘 원본 파일(LICENSE에 Qwen 2.5 고지가 들어 있다)과 변환 확인용 설정
cp "$out/hf/LICENSE" "$out/hf/config.json" "$out/hf/tokenizer_config.json" "$out/"
# 아래 명령들은 표준 입력을 막는다: 이 스크립트 자체가 표준 입력으로 들어오고 있어, 읽으면 뒤 줄을 먹는다
python3 /app/convert_hf_to_gguf.py "$out/hf" --outtype bf16 --outfile "$out/$NAME-bf16.gguf" < /dev/null
rm -rf "$out/hf"
/app/llama-quantize "$out/$NAME-bf16.gguf" "$out/$NAME-$QUANT.gguf" "$QUANT" < /dev/null
rm -f "$out/$NAME-bf16.gguf"
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
