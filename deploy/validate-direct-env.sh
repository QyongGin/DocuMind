#!/usr/bin/env sh
set -eu

ENV_FILE="${1:-.env}"
SERVER_IP="${2:-}"
FRONTEND_PORT="${3:-19580}"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

warn() {
  printf 'WARN: %s\n' "$1" >&2
}

value_of() {
  key="$1"
  line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
  [ -n "$line" ] || fail "${key} is missing in ${ENV_FILE}"
  printf '%s' "${line#*=}"
}

require_non_empty() {
  key="$1"
  value="$(value_of "$key")"
  [ -n "$value" ] || fail "${key} is empty"
  case "$value" in
    change-me*|*SERVER_IP*|*사용자가*|*32자*|*비밀번호*)
      fail "${key} still contains a placeholder: ${value}"
      ;;
  esac
}

[ -f "$ENV_FILE" ] || fail "${ENV_FILE} does not exist"
[ -n "$SERVER_IP" ] || fail "server IP is required. Usage: deploy/validate-direct-env.sh .env 34.64.63.109 19580"

required_keys="
MYSQL_ROOT_PASSWORD
MYSQL_DATABASE
JWT_SECRET
JWT_ACCESS_TOKEN_EXPIRATION
JWT_REFRESH_TOKEN_EXPIRATION
DOCUMIND_ADMIN_USERNAME
DOCUMIND_ADMIN_PASSWORD
APP_CORS_ALLOWED_ORIGINS
FRONTEND_HOST
FRONTEND_PORT
FASTAPI_CONNECT_TIMEOUT
FASTAPI_RESPONSE_TIMEOUT
FASTAPI_STREAM_TIMEOUT
DOCUMENT_PROCESSING_ASYNC_ENABLED
DOCUMENT_PROCESSING_CORE_POOL_SIZE
DOCUMENT_PROCESSING_MAX_POOL_SIZE
DOCUMENT_PROCESSING_QUEUE_CAPACITY
OLLAMA_BASE_URL
OLLAMA_LLM_MODEL
OLLAMA_EMBEDDING_MODEL
OLLAMA_KEEP_ALIVE
OLLAMA_EMBEDDING_WARMUP_ON_STARTUP
OLLAMA_NUM_CTX
OLLAMA_NUM_PREDICT
OLLAMA_NUM_THREAD
CHUNK_SIZE
CHUNK_OVERLAP
CHUNK_MERGE_MIN_SIZE
EMBEDDING_BATCH_SIZE
UPLOAD_READ_CHUNK_BYTES
CHAT_DEFAULT_TOP_K
AI_DEFAULT_TOP_K
VITE_DEFAULT_TOP_K
VITE_API_BASE_URL
"

for key in $required_keys; do
  require_non_empty "$key"
done

jwt_secret="$(value_of JWT_SECRET)"
[ "${#jwt_secret}" -ge 32 ] || fail "JWT_SECRET must be at least 32 characters"

configured_port="$(value_of FRONTEND_PORT)"
[ "$configured_port" = "$FRONTEND_PORT" ] || fail "FRONTEND_PORT=${configured_port}, expected ${FRONTEND_PORT}"

frontend_host="$(value_of FRONTEND_HOST)"
[ "$frontend_host" = "0.0.0.0" ] || fail "FRONTEND_HOST=${frontend_host}, expected 0.0.0.0 for direct IP testing"

allowed_origins="$(value_of APP_CORS_ALLOWED_ORIGINS)"
expected_origin="http://${SERVER_IP}:${FRONTEND_PORT}"
case ",${allowed_origins}," in
  *",${expected_origin},"*) ;;
  *) fail "APP_CORS_ALLOWED_ORIGINS must include ${expected_origin}. Current: ${allowed_origins}" ;;
esac

case "$allowed_origins" in
  *SERVER_IP*) fail "APP_CORS_ALLOWED_ORIGINS still contains SERVER_IP placeholder" ;;
esac

ollama_base_url="$(value_of OLLAMA_BASE_URL)"
[ "$ollama_base_url" = "http://ollama:11434" ] || warn "OLLAMA_BASE_URL=${ollama_base_url}; direct Docker GPU test usually uses http://ollama:11434"

admin_password="$(value_of DOCUMIND_ADMIN_PASSWORD)"
[ "${#admin_password}" -ge 8 ] || warn "DOCUMIND_ADMIN_PASSWORD is shorter than 8 characters"

chunk_size="$(value_of CHUNK_SIZE)"
chunk_overlap="$(value_of CHUNK_OVERLAP)"
[ "$chunk_overlap" -lt "$chunk_size" ] || fail "CHUNK_OVERLAP=${chunk_overlap} must be smaller than CHUNK_SIZE=${chunk_size}"

embedding_batch_size="$(value_of EMBEDDING_BATCH_SIZE)"
[ "$embedding_batch_size" -ge 1 ] || fail "EMBEDDING_BATCH_SIZE must be at least 1"

vite_api_base_url="$(value_of VITE_API_BASE_URL)"
[ "$vite_api_base_url" = "/api" ] || warn "VITE_API_BASE_URL=${vite_api_base_url}; nginx frontend mode usually uses /api"

printf 'OK: %s is valid for direct test origin %s\n' "$ENV_FILE" "$expected_origin"
