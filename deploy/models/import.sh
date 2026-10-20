#!/usr/bin/env bash
# 변환한 GGUF를 채팅 틀과 함께 데스크탑 Ollama에 등록하고, 틀이 공식 채팅 틀과 같은 입력을 만드는지 확인한다(ADR-0036).
#
# 사용법(데스크탑 WSL, 저장소 루트에서, compose의 ollama가 떠 있을 때): deploy/models/import.sh deploy/models/ax40light
# 읽는 파일: 볼륨 model_work 안 <NAME>/<NAME>-<QUANT>.gguf(convert.sh 결과, 또는 학습 서버에서 옮겨 온 파일)
# 이미 같은 이름이 등록돼 있으면 덮어쓰지 않고 멈춘다(바꿀 모델은 새 이름으로 등록하고 이전 모델을 남긴다, ADR-0011).
#
# 환경값: MODEL_VOLUME(기본 model_work), COMPOSE_PROJECT(기본 documind_desktop), OLLAMA_IMAGE(기본 ollama/ollama:latest),
#         OLLAMA_NAME(recipe.env 값을 덮어씀 — 등록 확인용으로 다른 이름에 올릴 때)
set -euo pipefail

dir=${1:?"모델 폴더를 준다. 예: deploy/models/ax40light"}
override_name=${OLLAMA_NAME:-}
# shellcheck source=/dev/null
source "$dir/recipe.env"
OLLAMA_NAME=${override_name:-$OLLAMA_NAME}
: "${NAME:?recipe.env에 NAME이 없다}" "${QUANT:?recipe.env에 QUANT가 없다}" "${OLLAMA_NAME:?recipe.env에 OLLAMA_NAME이 없다}"

VOLUME=${MODEL_VOLUME:-model_work}
NETWORK=${COMPOSE_PROJECT:-documind_desktop}_default
OLLAMA_IMAGE=${OLLAMA_IMAGE:-ollama/ollama:latest}
gguf=/work/$NAME/$NAME-$QUANT.gguf

ollama_cli() {
  docker run --rm --network "$NETWORK" -v "$VOLUME":/work -e OLLAMA_HOST=http://ollama:11434 \
    --entrypoint ollama "$OLLAMA_IMAGE" "$@" < /dev/null
}

if ollama_cli show "$OLLAMA_NAME" > /dev/null 2>&1; then
  echo "이미 등록돼 있음: $OLLAMA_NAME — 덮어쓰지 않는다. 새 모델이면 새 이름으로 등록한다" >&2
  exit 1
fi

# 채팅 틀은 저장소 파일을 쓴다. GGUF 안의 Jinja 틀은 Ollama가 그대로 쓰지 못한다.
sed "s#__GGUF__#$gguf#" "$dir/Modelfile.tmpl" \
  | docker run --rm -i -v "$VOLUME":/work --entrypoint sh "$OLLAMA_IMAGE" -c "cat > /work/$NAME/Modelfile"
ollama_cli create "$OLLAMA_NAME" -f "/work/$NAME/Modelfile"

if [ -n "${EXPECTED_PROMPT_TOKENS:-}" ]; then
  # 시스템 글 없이 "안녕하세요" 한 마디를 보내 Ollama가 센 입력 토큰 수를 공식 틀의 값과 비교한다
  stats=$(ollama_cli run --verbose "$OLLAMA_NAME" "안녕하세요" 2>&1)
  tokens=$(printf '%s\n' "$stats" | sed -n 's/^prompt eval count: *\([0-9]*\) token.*/\1/p' | head -1)
  if [ "$tokens" = "$EXPECTED_PROMPT_TOKENS" ]; then
    echo "채팅 틀 확인: 입력 토큰 $tokens개, 공식 틀과 같다"
  else
    echo "채팅 틀 확인 실패: 입력 토큰 ${tokens:-?}개, 공식 틀은 ${EXPECTED_PROMPT_TOKENS}개 — Modelfile.tmpl을 확인한다" >&2
    printf '%s\n' "$stats" >&2
    exit 1
  fi
fi
echo "등록함: $OLLAMA_NAME"
