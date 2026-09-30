# deploy/backup.sh와 deploy/restore.sh가 함께 쓰는 함수. 직접 실행하지 않는다.
# 컨테이너는 compose가 붙인 라벨로 찾으므로 어떤 compose 파일로 올렸는지와 관계없다.

fail() {
  printf '오류: %s\n' "$1" >&2
  exit 1
}

# container_of <프로젝트> <서비스>
container_of() {
  docker ps -aq \
    --filter "label=com.docker.compose.project=$1" \
    --filter "label=com.docker.compose.service=$2" | awk 'NR == 1'
}

is_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$1")" = true ]
}

# wait_healthy <컨테이너> <최대 대기 초>
wait_healthy() {
  local id="$1" timeout="$2" waited=0 status
  while :; do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id")"
    case "$status" in
      healthy | running) return 0 ;;
    esac
    [ "$waited" -lt "$timeout" ] \
      || fail "$(docker inspect -f '{{.Name}}' "$id") 컨테이너가 ${timeout}초 안에 준비되지 않았다 (상태: ${status})"
    sleep 2
    waited=$((waited + 2))
  done
}

# mysql 이미지는 처음 켤 때 초기화용 임시 서버(네트워크 없음)를 먼저 띄운다.
# compose 헬스체크(mysqladmin ping)는 로그인이 거부돼도 성공으로 보아 이때도 healthy가 되므로,
# 초기화가 끝난 서버에서만 되는 TCP 로그인으로 준비 여부를 판단한다.
# wait_mysql_ready <mysql 컨테이너> <최대 대기 초>
wait_mysql_ready() {
  local id="$1" timeout="$2" waited=0
  until docker exec "$id" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -h127.0.0.1 --protocol=TCP -e "SELECT 1"' >/dev/null 2>&1; do
    [ "$waited" -lt "$timeout" ] || fail "mysql이 ${timeout}초 안에 로그인을 받지 않았다"
    sleep 2
    waited=$((waited + 2))
  done
}

# 백업·복원은 chromadb의 볼륨을 빌려 쓰는 보조 컨테이너(--volumes-from)로 한다.
# /data가 볼륨이 아니면 색인이 컨테이너 안에만 있어서 보조 컨테이너가 보지 못한다.
require_chroma_volume() {
  [ -n "$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}ok{{end}}{{end}}' "$1")" ] \
    || fail "chromadb의 /data가 볼륨이 아니다. docker-compose.yml의 chroma_data 연결을 확인한다"
}

mysql_count_sql() {
  cat <<'SQL'
SET SESSION group_concat_max_len = 1000000;
SELECT GROUP_CONCAT(CONCAT('SELECT ''', table_name, ''', COUNT(*) FROM `', table_name, '`')
                    ORDER BY table_name SEPARATOR ' UNION ALL ')
  INTO @q
  FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE';
SET @q = IFNULL(@q, 'SELECT ''(none)'', 0');
PREPARE stmt FROM @q;
EXECUTE stmt;
SQL
}

# mysql_counts <mysql 컨테이너>: "mysql<TAB>테이블<TAB>행 수"를 출력한다.
# mysql 명령은 컨테이너 안에서 돌고 비밀번호는 컨테이너의 환경변수에서 읽으므로,
# 호스트의 명령줄이나 스크립트에 비밀번호가 남지 않는다.
mysql_counts() {
  mysql_count_sql \
    | docker exec -i "$1" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B "$MYSQL_DATABASE"' \
    | awk -F'\t' '{ print "mysql\t" $1 "\t" $2 }'
}

# chroma_counts <프로젝트>: "chroma<TAB>컬렉션<TAB>건수"를 출력한다.
# ai-server 컨테이너 안의 chromadb 클라이언트로 센다. ai-server가 없거나 꺼져 있으면 실패한다.
chroma_counts() {
  local ai
  ai="$(container_of "$1" ai-server)"
  if [ -z "$ai" ] || ! is_running "$ai"; then
    return 1
  fi
  docker exec "$ai" python -c '
import os
import chromadb

client = chromadb.HttpClient(host=os.environ["CHROMA_HOST"], port=int(os.environ["CHROMA_PORT"]))
for collection in sorted(client.list_collections(), key=lambda c: c.name):
    print(f"chroma\t{collection.name}\t{collection.count()}")
'
}
