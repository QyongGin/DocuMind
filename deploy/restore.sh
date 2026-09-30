#!/usr/bin/env bash
# deploy/backup.sh로 만든 백업으로 DB(MySQL)와 검색 색인(Chroma)을 되돌린다.
#
# 사용법: deploy/restore.sh <백업 폴더> <compose 프로젝트 이름>
#   예:   deploy/restore.sh ~/backups/documind/20260930-223000 documind_desktop
#
# 대상 프로젝트의 DB와 색인을 지우고 백업 내용으로 바꾼다. 되돌릴 수 없으므로
# 실행하면 프로젝트 이름을 한 번 더 입력받는다. 필요하면 먼저 지금 상태를 백업한다.
#
# - 대상 프로젝트에 mysql·chromadb 컨테이너가 있어야 한다. 새 서버라면 스택을 한 번 올린 뒤 실행한다.
# - 복원하는 동안 backend와 ai-server를 멈췄다가, 켜져 있던 것만 다시 켠다.
#   ai-server가 메모리에 들고 있던 검색 캐시(BM25)도 이때 비워져 복원된 색인 기준으로 다시 만들어진다.
# - 끝나면 테이블별 행 수와 컬렉션별 건수를 백업 때 기록(manifest.txt)과 비교한다. 다르면 종료 코드 1.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/backup-common.sh"

BACKUP_DIR="${1:-}"
PROJECT="${2:-}"

if [ -z "$BACKUP_DIR" ] || [ -z "$PROJECT" ]; then
  fail "사용법: deploy/restore.sh <백업 폴더> <compose 프로젝트 이름>"
fi
for file in mysql.sql.gz chroma-data.tar.gz manifest.txt SHA256SUMS; do
  [ -f "$BACKUP_DIR/$file" ] || fail "${BACKUP_DIR}에 ${file}이 없다"
done
(cd "$BACKUP_DIR" && sha256sum --check --quiet SHA256SUMS) \
  || fail "체크섬이 맞지 않는다. 백업 파일이 손상됐다"

MYSQL="$(container_of "$PROJECT" mysql)"
CHROMA="$(container_of "$PROJECT" chromadb)"
if [ -z "$MYSQL" ] || [ -z "$CHROMA" ]; then
  fail "프로젝트 '${PROJECT}'에 mysql·chromadb 컨테이너가 없다. 새 서버라면 스택을 한 번 올린 뒤 실행한다"
fi
require_chroma_volume "$CHROMA"
AI="$(container_of "$PROJECT" ai-server)"
BACKEND="$(container_of "$PROJECT" backend)"

printf '백업: %s\n' "$BACKUP_DIR"
awk -F'\t' '$1 == "created_at" || $1 == "project" || $1 == "repo_commit" { print "  " $1 ": " $2 }' \
  "$BACKUP_DIR/manifest.txt"
printf '대상 프로젝트: %s\n' "$PROJECT"
printf '대상의 DB와 색인을 지우고 백업 내용으로 바꾼다. 되돌릴 수 없다.\n'
printf '계속하려면 프로젝트 이름(%s)을 입력한다: ' "$PROJECT"
answer=""
read -r answer || true
[ "$answer" = "$PROJECT" ] || fail "입력이 프로젝트 이름과 달라 아무것도 바꾸지 않고 멈췄다"

trap 'printf "\n복원이 끝나지 않았다. backend·ai-server는 멈춘 상태로 둔다. 원인을 고친 뒤 다시 실행한다.\n" >&2' EXIT

echo "[1/4] backend·ai-server 정지 (복원 중인 DB·색인을 쓰지 않도록)"
restart_ai=false
restart_backend=false
if [ -n "$BACKEND" ] && is_running "$BACKEND"; then
  docker stop "$BACKEND" >/dev/null
  restart_backend=true
fi
if [ -n "$AI" ] && is_running "$AI"; then
  docker stop "$AI" >/dev/null
  restart_ai=true
fi

echo "[2/4] mysql 복원"
is_running "$MYSQL" || docker start "$MYSQL" >/dev/null
wait_mysql_ready "$MYSQL" 180
gzip -dc "$BACKUP_DIR/mysql.sql.gz" \
  | docker exec -i "$MYSQL" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot'

echo "[3/4] chroma 복원"
if is_running "$CHROMA"; then
  docker stop "$CHROMA" >/dev/null
fi
gzip -dc "$BACKUP_DIR/chroma-data.tar.gz" \
  | docker run --rm -i --network none --volumes-from "$CHROMA" \
      --entrypoint sh "$(docker inspect -f '{{.Image}}' "$CHROMA")" \
      -c 'find /data -mindepth 1 -delete && tar -xf - -C /'
docker start "$CHROMA" >/dev/null
wait_healthy "$CHROMA" 120

echo "[4/4] 멈췄던 서비스 다시 켜기"
if $restart_ai; then
  docker start "$AI" >/dev/null
  wait_healthy "$AI" 300
fi
if $restart_backend; then
  docker start "$BACKEND" >/dev/null
  wait_healthy "$BACKEND" 300
fi
trap - EXIT

mismatch=false
compare_counts() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    printf '%s: 백업 때와 같다\n' "$label"
  else
    printf '%s: 백업 때와 다르다 (< 백업 때, > 지금)\n' "$label"
    diff <(printf '%s\n' "$expected") <(printf '%s\n' "$actual") || true
    mismatch=true
  fi
}

printf '\n'
compare_counts "mysql 테이블별 행 수" \
  "$(awk -F'\t' '$1 == "mysql"' "$BACKUP_DIR/manifest.txt")" "$(mysql_counts "$MYSQL")"
expected_chroma="$(awk -F'\t' '$1 == "chroma"' "$BACKUP_DIR/manifest.txt")"
if [ -z "$expected_chroma" ]; then
  echo "chroma 컬렉션별 건수: 백업 때 기록이 없어 비교하지 않았다"
elif actual_chroma="$(chroma_counts "$PROJECT")"; then
  compare_counts "chroma 컬렉션별 건수" "$expected_chroma" "$actual_chroma"
else
  echo "chroma 컬렉션별 건수: ai-server가 없거나 꺼져 있어 비교하지 못했다"
fi

if $mismatch; then
  fail "복원은 끝났지만 건수가 백업 때와 다르다. 위 차이를 확인한다"
fi
printf '\n복원 완료: %s → %s\n' "$BACKUP_DIR" "$PROJECT"
