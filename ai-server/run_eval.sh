#!/usr/bin/env bash
# R0-3: RAG 평가 원샷 스크립트.
#
# 목적: 사람이 SSH 로 매번 손으로 하던 평가 절차(서버 준비 대기 -> 평가 실행 ->
#       결과 회수)를 한 번 호출로 끝내고, 두 가지 함정을 차단한다.
#   (1) readiness 미대기 함정: ai-server 가 아직 안 떴는데 평가를 돌려 0/40 이 나오는 것.
#   (2) /tmp 휘발 함정: 컨테이너 /tmp 에 결과를 쓰면 재빌드 때 사라지는 것
#       -> 결과를 host 영속 경로(OUT_DIR)로 회수한다.
#
# 사용 예 (데스크탑):
#   # host 에서 컨테이너 published 포트로 평가 + 결과를 host repo 아래로 회수
#   OUT_DIR=~/DocuMind/eval-results ./ai-server/run_eval.sh
#   # 또는 컨테이너 안에서:
#   docker compose exec ai-server bash -lc 'OUT_DIR=/data/eval ./run_eval.sh'
#   # 추가 인자는 그대로 evaluate_rag.py 로 전달된다:
#   ./ai-server/run_eval.sh --fail-on-miss --limit 5
#
# 환경변수:
#   BASE_URL        평가 대상 ai-server (기본 http://localhost:8000)
#   PYTHON_BIN      python 실행기 (기본: venv 있으면 venv/bin/python, 없으면 python3)
#   OUT_DIR         결과 JSON/CSV 회수 경로 (기본 ./eval-results) — host 영속 경로 권장
#   READY_TIMEOUT   /health 대기 최대 초 (기본 60)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BASE_URL="${BASE_URL:-http://localhost:8000}"
OUT_DIR="${OUT_DIR:-./eval-results}"
READY_TIMEOUT="${READY_TIMEOUT:-60}"

# PYTHON_BIN 기본값: 같은 디렉터리의 venv 를 우선 사용한다.
if [ -z "${PYTHON_BIN:-}" ]; then
  if [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
JSON_OUT="$OUT_DIR/eval-$STAMP.json"
CSV_OUT="$OUT_DIR/eval-$STAMP.csv"

echo "[run_eval] base_url=$BASE_URL"
echo "[run_eval] python=$PYTHON_BIN"
echo "[run_eval] out_dir=$OUT_DIR (host 영속 경로여야 결과가 보존된다)"

# 1) 결정론 경고: temperature 가 0 이 아니면 같은 코드도 점수가 흔들린다.
case "${OLLAMA_TEMPERATURE:-unset}" in
  0|0.0) : ;;
  *) echo "[run_eval] WARN: OLLAMA_TEMPERATURE=${OLLAMA_TEMPERATURE:-unset} — 결정론 측정에는 0 이어야 한다(17/40 재현 불가 위험)." >&2 ;;
esac

# 2) readiness 폴링: /health 가 응답해야 평가를 시작한다(0/40 함정 차단).
echo "[run_eval] /health readiness 대기 (최대 ${READY_TIMEOUT}s)..."
deadline=$(( $(date +%s) + READY_TIMEOUT ))
until curl -fsS "$BASE_URL/health" >/dev/null 2>&1; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "[run_eval] ERROR: ${READY_TIMEOUT}s 내에 $BASE_URL/health 응답 없음. ai-server 기동을 먼저 확인하라." >&2
    exit 1
  fi
  sleep 2
done
echo "[run_eval] /health OK"

# 3) RAG 경로 사전 확인: 대표 질문 1개가 trace 응답을 내는지(서버는 떴지만 색인이
#    비었거나 RAG 경로가 깨진 경우를 본 평가 전에 잡는다). 실패해도 경고만 하고 진행.
echo "[run_eval] /debug/rag-trace 사전 확인..."
if ! curl -fsS -X POST "$BASE_URL/debug/rag-trace" \
      -H 'Content-Type: application/json' \
      -d '{"question":"원서 접수 비용은 얼마인가요?","top_k":5}' >/dev/null 2>&1; then
  echo "[run_eval] WARN: /debug/rag-trace 사전 확인 실패 — 색인이 비었거나 RAG 경로 문제일 수 있다. 평가는 계속한다." >&2
fi

# 4) 평가 실행 (trace + query). 결과를 host 경로로 회수.
echo "[run_eval] evaluate_rag.py 실행 (trace + query)..."
"$PYTHON_BIN" "$SCRIPT_DIR/evaluate_rag.py" \
  --base-url "$BASE_URL" \
  --include-query \
  --output "$JSON_OUT" \
  --csv-output "$CSV_OUT" \
  "$@"

echo "[run_eval] 완료."
echo "[run_eval]   JSON: $JSON_OUT"
echo "[run_eval]   CSV : $CSV_OUT"
