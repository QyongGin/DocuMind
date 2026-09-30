#!/usr/bin/env bash
# DocuMind의 DB(MySQL)와 검색 색인(Chroma)을 한 폴더에 백업한다.
#
# 사용법: deploy/backup.sh <compose 프로젝트 이름>
#   예:   deploy/backup.sh documind_desktop
#
# 결과: ${BACKUP_ROOT:-$HOME/backups/documind}/<날짜-시각>/
#   mysql.sql.gz        mysqldump 결과. 복원하면 DB를 지우고 이 내용으로 다시 만든다
#   chroma-data.tar.gz  chromadb 컨테이너의 /data 전체
#   manifest.txt        만든 시각, 이미지, 테이블별 행 수, 컬렉션별 건수 (탭 구분)
#   SHA256SUMS          위 세 파일의 체크섬
#
# Chroma 파일이 쓰이는 도중에 복사되지 않도록 백업하는 동안(수 초) chromadb를 멈춘다.
# 그동안 질문과 업로드가 실패하므로 사용하는 사람이 없을 때 실행한다.
# 복원은 deploy/restore.sh로 한다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/backup-common.sh"

PROJECT="${1:-}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/backups/documind}"

[ -n "$PROJECT" ] || fail "compose 프로젝트 이름이 필요하다. 예: deploy/backup.sh documind_desktop"

MYSQL="$(container_of "$PROJECT" mysql)"
CHROMA="$(container_of "$PROJECT" chromadb)"
if [ -z "$MYSQL" ] || [ -z "$CHROMA" ]; then
  fail "프로젝트 '${PROJECT}'에 mysql·chromadb 컨테이너가 없다. docker ps -a로 프로젝트 이름을 확인한다"
fi
if ! is_running "$MYSQL" || ! is_running "$CHROMA"; then
  fail "mysql·chromadb가 실행 중이어야 한다"
fi
require_chroma_volume "$CHROMA"

DEST="${BACKUP_ROOT}/$(date +%Y%m%d-%H%M%S)"
WORK="${DEST}.partial"
if [ -e "$DEST" ] || [ -e "$WORK" ]; then
  fail "이미 있는 폴더다: ${DEST}"
fi
mkdir -p "$WORK"
printf '백업 폴더: %s\n' "$DEST"

echo "[1/4] chroma 컬렉션 건수 확인"
if ! chroma_lines="$(chroma_counts "$PROJECT")"; then
  chroma_lines=$'chroma_note\t건수 확인 못 함 (ai-server가 없거나 꺼져 있음)'
fi

echo "[2/4] chromadb 정지 (백업이 끝나면 다시 켠다)"
docker stop "$CHROMA" >/dev/null
trap 'docker start "$CHROMA" >/dev/null' EXIT

echo "[3/4] mysql 덤프, chroma /data 복사"
docker exec "$MYSQL" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --hex-blob --add-drop-database --databases "$MYSQL_DATABASE"' \
  | gzip > "$WORK/mysql.sql.gz"
mysql_lines="$(mysql_counts "$MYSQL")"
docker run --rm --network none --volumes-from "$CHROMA" \
  --entrypoint tar "$(docker inspect -f '{{.Image}}' "$CHROMA")" -cf - -C / data \
  | gzip > "$WORK/chroma-data.tar.gz"

docker start "$CHROMA" >/dev/null
trap - EXIT
wait_healthy "$CHROMA" 120

echo "[4/4] 백업 파일 확인, manifest·체크섬 기록"
case "$(gzip -dc "$WORK/mysql.sql.gz" | tail -n 1)" in
  "-- Dump completed"*) ;;
  *) fail "mysql 덤프가 끝까지 쓰이지 않았다: ${WORK}/mysql.sql.gz" ;;
esac
tar -tzf "$WORK/chroma-data.tar.gz" \
  | awk '$0 == "data/chroma.sqlite3" { found = 1 } END { exit !found }' \
  || fail "chroma 백업에 data/chroma.sqlite3가 없다: ${WORK}/chroma-data.tar.gz"

{
  printf 'created_at\t%s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)"
  printf 'project\t%s\n' "$PROJECT"
  printf 'repo_commit\t%s\n' "$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  printf 'mysql_image\t%s\n' "$(docker inspect -f '{{.Config.Image}} {{.Image}}' "$MYSQL")"
  printf 'chroma_image\t%s\n' "$(docker inspect -f '{{.Config.Image}} {{.Image}}' "$CHROMA")"
  printf '%s\n' "$mysql_lines" "$chroma_lines"
} > "$WORK/manifest.txt"
(cd "$WORK" && sha256sum mysql.sql.gz chroma-data.tar.gz manifest.txt > SHA256SUMS)
mv "$WORK" "$DEST"

printf '\n완료: %s\n' "$DEST"
du -h "$DEST/mysql.sql.gz" "$DEST/chroma-data.tar.gz"
cat "$DEST/manifest.txt"
