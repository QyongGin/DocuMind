# DB·색인 백업·복원 절차

> **현행 문서** (2026-09-30, 총괄계획 M0-7). 지금의 데스크탑과 이후 학교 서버에 똑같이 쓴다.
> 스크립트: `deploy/backup.sh`, `deploy/restore.sh` (공통 함수 `deploy/backup-common.sh`). 리눅스(WSL 포함)에서 실행한다.
> 데스크탑을 켜고 끄는 절차는 `docs/development/local-gpu/데스크탑-작업-시작-종료-절차.md`를 본다.

## 1. 무엇을 백업하나

| 대상 | 내용 | 백업 여부 |
|---|---|---|
| MySQL `documind` DB | 사용자, 문서 목록, 카테고리, 대화 기록, 피드백, Flyway 이력 | ✅ `mysql.sql.gz` |
| Chroma `/data` 볼륨 | 검색 색인 전체 (컬렉션 `documents`·`retrieval_chunks`·`source_blocks`) | ✅ `chroma-data.tar.gz` |
| Ollama 모델 | EXAONE, qwen3-embedding | ❌ 다시 받으면 된다 (`docker-compose.gpu.yml`의 pull 서비스) |
| 업로드 원본 파일 | PDF·DOCX 등 | ❌ **서버에 남지 않는다.** 백엔드는 업로드 파일을 임시 파일로만 쓰고 지운다(`DocumentService.java`). 원본은 맥북 `Assets/`(M1부터 `Assets/corpus/`)에 보관한다 |
| `.env` | 비밀번호, JWT 비밀키 | ❌ 백업 폴더에 넣지 않는다. 따로 안전하게 보관한다 |

상태를 가진 곳은 MySQL과 Chroma 둘뿐이다. ai-server의 BM25 검색 캐시는 Chroma에서 다시 만드는 메모리 캐시라 백업할 필요가 없다.

> **개인정보 주의**: 백업에는 대화 기록(질문 원문)과 비밀번호 해시가 들어 있다. 백업의 보관 기간과 파기는 개인정보 처리 기준(D5, M4)에 포함해야 한다.

## 2. 백업

맥북에서 실행한다. 20초 안팎 걸린다.

```bash
ssh desktop 'cd ~/DocuMind && deploy/backup.sh documind_desktop'
```

결과는 데스크탑 `~/backups/documind/<날짜-시각>/`에 생긴다. 다른 위치에 두려면 앞에 `BACKUP_ROOT=<폴더>`를 붙인다.

| 파일 | 내용 |
|---|---|
| `mysql.sql.gz` | mysqldump 결과. 복원하면 DB를 지우고 이 내용으로 다시 만든다 (`--add-drop-database`) |
| `chroma-data.tar.gz` | chromadb 컨테이너의 `/data` 전체 |
| `manifest.txt` | 만든 시각, 저장소 커밋, 이미지, **테이블별 행 수, 컬렉션별 건수** (탭 구분). 복원 후 비교 기준 |
| `SHA256SUMS` | 위 세 파일의 체크섬. 복원할 때 먼저 확인한다 |

스크립트가 하는 일:

1. ai-server를 통해 Chroma 컬렉션별 건수를 센다.
2. **chromadb를 멈춘다.** 이때부터 질문과 업로드가 실패하므로 사용하는 사람이 없을 때 실행한다.
3. MySQL을 덤프하고 행 수를 센 뒤, Chroma `/data`를 압축해 복사한다.
4. chromadb를 다시 켠다. 도중에 실패해도 chromadb는 다시 켠다.
5. 덤프가 끝까지 쓰였는지, 압축 파일에 `chroma.sqlite3`가 있는지 확인하고 manifest와 체크섬을 쓴다.
6. 끝까지 성공해야 폴더 이름에서 `.partial`이 빠진다. `.partial`이 남아 있으면 실패한 백업이다.
7. 마지막으로 chromadb가 다시 준비됐는지 확인한다. 백업을 먼저 확정하므로, chromadb가 다시 켜지지 않는 경우에도 방금 만든 백업으로 복원할 수 있다.

**언제 하나**: 문서를 대량으로 올리거나 지우기 전, 색인·DB 구조가 바뀌는 배포 전, 중요한 작업을 끝낸 뒤.

**맥북으로 복사** (백업이 같은 디스크에 있으면 디스크 고장에는 대비가 안 된다):

```bash
scp -r desktop:backups/documind/<날짜-시각> <맥북 보관 폴더>/
```

오래된 백업은 자동으로 지우지 않는다. 필요 없는 폴더는 사용자가 직접 지운다.

## 3. 복원

**대상의 DB와 색인을 지우고 백업 내용으로 바꾼다. 되돌릴 수 없다.** 필요하면 먼저 지금 상태를 백업한다.

```bash
ssh -t desktop 'cd ~/DocuMind && deploy/restore.sh ~/backups/documind/<날짜-시각> documind_desktop'
```

실행하면 백업 정보가 나오고, 프로젝트 이름(`documind_desktop`)을 한 번 더 입력해야 진행한다. 다르게 입력하면 아무것도 바꾸지 않고 멈춘다.

스크립트가 하는 일:

1. `SHA256SUMS`로 백업 파일이 손상되지 않았는지 확인한다.
2. backend·ai-server를 멈춘다 (복원 중인 DB·색인을 쓰지 않도록).
3. MySQL이 **초기화까지 끝난 상태**인지 확인한 뒤 덤프를 넣는다 (§5.4).
4. chromadb를 멈추고 `/data`를 비운 뒤 백업을 풀고 다시 켠다.
5. 멈췄던 ai-server·backend를 다시 켠다. ai-server가 메모리에 들고 있던 검색 캐시도 이때 비워진다.
6. 테이블별 행 수와 컬렉션별 건수를 `manifest.txt`와 비교한다. 다르면 차이를 보여 주고 종료 코드 1로 끝난다.

도중에 실패하면 backend·ai-server는 멈춘 상태로 둔다. 반쯤 복원된 데이터로 서비스하지 않기 위해서다. 원인을 고친 뒤 다시 실행하면 처음부터 다시 복원한다.

**새 서버에 복원할 때**: 먼저 `docker compose ... up -d`로 스택을 한 번 올려 컨테이너와 빈 볼륨을 만든 뒤 실행한다.

**버전이 다른 코드에 복원할 때**: 옛 백업을 새 코드에 넣으면 backend가 켜질 때 Flyway가 스키마를 올린다. 새 백업을 옛 코드에 넣으면 backend가 스키마 검증(`ddl-auto: validate`)에서 멈출 수 있다.

## 4. 복원 리허설 (운영 데이터를 건드리지 않는 확인)

백업이 실제로 복원되는지는 복원해 봐야 안다. 운영 프로젝트와 따로 떨어진 임시 프로젝트(`documind_restoretest`)에 MySQL·Chroma만 띄워 그곳에 복원한다. MySQL과 Chroma는 호스트 포트를 열지 않으므로(`expose`만 사용) 운영 스택과 충돌하지 않는다.

```bash
# 1) 임시 프로젝트에 MySQL·Chroma만 띄운다 (새 볼륨이 생긴다)
ssh desktop 'cd ~/DocuMind && docker compose --project-name documind_restoretest -f docker-compose.yml --env-file .env up -d --wait --pull never mysql chromadb'

# 2) 복원한다 (확인 입력을 파이프로 넘긴다)
ssh desktop 'cd ~/DocuMind && printf "documind_restoretest\n" | deploy/restore.sh ~/backups/documind/<날짜-시각> documind_restoretest'

# 3) 정리한다. 임시 프로젝트만 지운다 (down -v는 쓰지 않고 볼륨 이름을 직접 적는다)
ssh desktop 'cd ~/DocuMind && docker compose --project-name documind_restoretest -f docker-compose.yml --env-file .env down && docker volume rm documind_restoretest_mysql_data documind_restoretest_chroma_data'
```

임시 프로젝트에는 ai-server가 없어서 스크립트가 Chroma 건수를 비교하지 못한다. Chroma는 ai-server 이미지로 임시 컨테이너를 띄워 확인한다 (`docker run --rm -i --pull never --network documind_restoretest_default --entrypoint python documind_desktop-ai-server -`에 chromadb 클라이언트 코드를 넘긴다. `host="chromadb"`).

### 4.1 2026-09-30 리허설 기록

| 확인 | 결과 |
|---|---|
| 백업 (운영 `documind_desktop`) | 첫 코드 16초, **최종 코드(`321c9b0`) 13초**. `mysql.sql.gz` 36KB, `chroma-data.tar.gz` 55MB (원본 약 257MB), 체크섬 3개 OK |
| 백업 뒤 운영 서비스 | 6개 컨테이너 healthy 유지, 질문 HTTP 200 (2.1초) |
| 확인 입력을 틀렸을 때 | 종료 코드 1, 임시 DB 테이블 0개 그대로 (아무것도 바뀌지 않음) |
| 복원 (임시 `documind_restoretest`) | 9초. 스크립트의 MySQL 행 수 비교: 백업 때와 같음. 최종 코드로 한 번 더: 새로 만든 MySQL에 곧바로 복원해 9초, 결과 같음 |
| MySQL 내용 | 복원된 DB를 다시 덤프해 원본 덤프와 비교: **덤프 시각 한 줄 외 동일** (286줄, 두 번 모두) |
| Chroma 내용 | 운영본과 복원본에서 컬렉션별 id·본문·메타데이터·임베딩(2,560차원) 해시 비교: **3개 컬렉션 모두 동일** (documents 2,695 · retrieval_chunks 214 · source_blocks 253, 두 번 모두) |
| 정리 | 임시 컨테이너 2개·볼륨 2개·네트워크 1개 삭제, 운영 스택·볼륨 3개 그대로 |
| 돌려 보지 못한 부분 | 임시 프로젝트에는 backend·ai-server가 없어서, **운영 프로젝트에 복원할 때 두 서비스를 멈췄다 다시 켜는 단계와 복원 후 Chroma 건수 비교는 실행되지 않았다.** 건수를 세는 함수는 백업 때 운영 ai-server로 실행됐다 |

백업 당시 테이블별 행 수: categories 0 · chat_feedback 1 · chat_messages 66 · chat_sessions 65 · documents 4 · flyway_schema_history 3 · prompt_config 0 · users 1.

백업 폴더 (데스크탑): `~/backups/documind/20260930-222436/`(첫 리허설), `20260930-222921/`(중간 코드), `20260930-223615/`(최종 코드, 두 번째 리허설). M0-1의 `~/backups/chroma/20260930-181322/`(Chroma만, 257MB)도 남아 있다.

## 5. 설계 이유

### 5.1 Chroma를 멈추고 복사한다

Chroma 1.x는 메타데이터를 SQLite(`chroma.sqlite3`)에, 벡터를 컬렉션별 HNSW 바이너리 파일에 나눠 쓴다. 쓰는 도중에 파일을 복사하면 두 파일의 시점이 어긋날 수 있다. 몇 초 멈추는 대가로 일관된 사본을 얻는다.

### 5.2 보조 컨테이너로 볼륨을 읽고 쓴다

백업과 복원 모두 chromadb 컨테이너의 볼륨을 빌린 보조 컨테이너(`docker run --volumes-from`)로 한다. 같은 이미지를 쓰므로 `tar`·`find`가 확실히 있고, 복원 때 `/data`를 비우는 일도 같은 방식으로 할 수 있다. 대신 `/data`가 볼륨이 아니면 색인이 컨테이너 안에만 있어서 보조 컨테이너가 보지 못한다. 그래서 두 스크립트 모두 `/data`가 볼륨인지 먼저 확인한다. 2026-09-30 이전에 실제로 이 상태였다(D1, #115).

### 5.3 비밀번호를 호스트에 두지 않는다

`mysql`·`mysqldump`는 MySQL 컨테이너 안에서 실행하고, 비밀번호는 컨테이너가 이미 가진 환경변수(`MYSQL_ROOT_PASSWORD`)에서 읽는다(`MYSQL_PWD`). 호스트 명령줄, 프로세스 목록, 스크립트, 백업 폴더 어디에도 비밀번호가 남지 않는다.

### 5.4 MySQL 준비 여부는 TCP 로그인으로 판단한다 (리허설에서 발견)

MySQL 공식 이미지는 처음 켤 때 초기화용 임시 서버(네트워크 없이 소켓만)를 먼저 띄우고, 초기화가 끝나면 실제 서버로 다시 켠다. compose 헬스체크 `mysqladmin ping`은 **로그인이 거부돼도 서버가 살아 있으면 성공**으로 보기 때문에, 초기화 도중에도 healthy가 된다. 새 서버에 스택을 올리고 바로 복원하면 이 틈에 복원이 실패하거나 중간에 끊길 수 있다.

리허설에서 새 MySQL을 띄워 시각을 쟀다 (UTC):

| 시각 | 일어난 일 |
|---|---|
| 13:26:42.46 | 임시 서버 시작 |
| 13:26:44.02 | compose 헬스체크 healthy (**처음 코드는 여기서 진행했다**) |
| 13:26:46 | 초기화 완료 |
| 13:26:48.71 | 실제 서버 준비 (포트 3306) |
| 13:26:48.74 | TCP 로그인 확인 통과 (**고친 코드는 여기서 진행한다**) |

임시 서버는 네트워크를 열지 않으므로, 비밀번호로 TCP 로그인이 되면 초기화가 끝난 실제 서버다(`wait_mysql_ready`).

## 6. 한계와 다음 단계

| 한계 | 영향 | 다음 단계 |
|---|---|---|
| MySQL과 Chroma를 몇 초 차이로 따로 뜬다 (한 시점의 스냅샷이 아님) | 백업하는 순간 업로드가 있으면 둘이 어긋날 수 있다 | 사용자가 없을 때 실행. 학교 운영(M6) 때 업로드를 막고 뜨는 방식 검토 |
| 백업이 같은 디스크에 있다 | 디스크 고장에는 대비가 안 된다 | 중요한 시점엔 맥북으로 복사. 학교 서버에서는 다른 디스크·서버로 복사 |
| 자동 실행·보관 기간이 없다 | 사람이 잊으면 백업이 없다 | 데스크탑은 작업할 때만 켜므로 지금은 수동. 학교 서버(M4 인계 패키지)에서 정기 실행·보관 기간을 정한다 |
| 복원 후 Chroma 건수 비교는 ai-server가 켜져 있을 때만 된다 | 임시 프로젝트 리허설에서는 따로 확인해야 한다 | 필요하면 리허설용 확인 스크립트를 추가 |

### 6.1 리허설에서 발견한 데이터 문제: DB와 색인이 서로 다른 문서를 들고 있다

| 저장소 | 들고 있는 문서 |
|---|---|
| MySQL `documents` | id 1~4. 6월 6~17일 웹에서 업로드. 활성은 3(2026 모집요강)·4(학칙) 두 개, 1·2는 비활성 |
| Chroma 색인 | document_id 101~105. 6월 29일 평가를 위해 **백엔드를 거치지 않고 ai-server에 직접 업로드**한 5개 문서 (`docs/archive/rag/issue-73/멀티포맷-평가셋-구축-및-1차-기준점-측정-보고서-20260629.md`) |

지금 챗봇의 답은 DB에 없는 문서(101~105)에서 나오고, 관리 화면의 문서 목록(1~4)은 색인에 청크가 없다. 백업은 두 저장소를 있는 그대로 담으므로 백업·복원의 문제는 아니다. **M1에서 실제 문서를 색인할 때는 반드시 백엔드 업로드 경로를 거쳐 DB와 색인을 맞추고, 직접 업로드한 101~105는 정리한다.**

## 7. 면접 포인트

- "백업은 복원해 봐야 백업이다. 운영 데이터를 건드리지 않으려고 별도 compose 프로젝트에 복원했고, 건수뿐 아니라 덤프를 다시 떠서 원본과 비교하고 벡터까지 해시로 비교했다."
- "리허설에서 MySQL 헬스체크가 초기화 도중에도 healthy가 된다는 것을 시각을 재서 확인했다. `mysqladmin ping`은 로그인 거부도 성공으로 본다. 그래서 준비 여부를 TCP 로그인으로 바꿨다."
- "파이프라인 실패를 놓치지 않으려고 `set -o pipefail`을 쓰는 bash로 작성했다. 없으면 `mysqldump | gzip`에서 덤프가 실패해도 gzip이 성공해서 빈 백업이 정상처럼 보인다."
