# 학교 문서 수집기와 문서 대장 (`tools/corpus`)

인하공업전문대학 누리집의 **공개** 안내 페이지·게시판 글·첨부를 모아 문서 대장(SQLite 파일 하나)에 기록한다.
수집한 문서는 M1에서 서비스 색인과 평가셋을 만드는 재료가 된다. 수집 원본과 대장은 저장소 밖(`Assets/corpus/`, git 제외)에 둔다.

## 수집 범위

| 묶음 | 내용 |
|---|---|
| 본교 안내 페이지 | 본교 사이트맵의 메뉴 페이지. 본문 영역만 저장하고, 게시판 목록만 있는 페이지는 행을 만들지 않는다 |
| 학사규정 | 정보목록 게시판의 '학사규정' 분류 첨부(PDF) |
| FAQ | 학교 FAQ·입시 FAQ. 문답 하나가 한 행 |
| 입학 | 전형별 모집요강 PDF(뷰어의 출력용 파일), 전년도 입시결과 PDF, 입시 안내 페이지 일부 |
| 학과 사이트 | 학과 사이트 29곳의 안내·교과과정 페이지. 학과 공지·갤러리·신청 기능은 넣지 않는다 |
| 공지 | 본교 공지 5종(학사·장학·행사·채용·일반)과 입학 공지의 **최근 3년** 글 본문과 첨부 |

입학 사이트의 지원자 기능(원서접수·합격자 조회·등록금 환불 신청 등), 로그인·관리자 경로, 대학알리미(robots.txt가 전체를 막음)는 받지 않는다.

## 수집 규칙 (코드로 강제)

| 규칙 | 구현 |
|---|---|
| robots.txt를 호스트마다 읽고 막힌 주소는 요청하지 않는다 | `polite.PoliteSession.allowed` — 표준 해석기가 못 읽는 `*`·`$` 규칙도 따로 해석 |
| 요청은 한 번에 하나, 시작 간격 2초 이상 | `PoliteSession._wait_turn`, `--interval`은 2 미만이면 거부 |
| User-Agent에 프로젝트 이름 | `DocuMind-corpus-collector/0.1 (...)`, 이메일은 넣지 않는다 |
| 403·429·5xx가 이어지면 간격을 두 배로, 5번 연속이면 멈춘다 | `PoliteSession.get` (간격 상한 30초) |
| 이어 받기 | 끝까지 처리한 단위(페이지·글·FAQ 게시판)를 `visits`에 적고 다음 실행에서 건너뛴다. 실패가 있었던 단위는 다시 시도한다 |
| 같은 내용은 한 번만 | SHA256이 같은 파일은 새로 쓰지 않고 먼저 받은 파일을 가리키며, 비고에 `내용 중복`을 적고 색인에서 뺀다 |
| 글은 모두 대장에 | 그림만 있는 글(포스터)은 `image_heavy=1` 행, 글·그림·첨부가 모두 없는 글은 색인 제외 행으로 남긴다. 본문 없이 첨부만 있는 글은 첨부 행의 `parent_id`로 남는다 |
| 빈 첨부 | 학교 사이트가 0바이트로 내려주는 첨부는 원본 없이 `빈 파일` 행만 남긴다 |
| HWP·HWPX | 확장자를 믿지 않고 내용으로 판단한다(`.hwp`인데 내용은 HWPX인 첨부가 있다) |
| 첨부 하나 100MB 상한 | 넘으면 받지 않고 실패 목록에 남긴다 |

## 개인정보 2단계 검사

```text
제목·첨부 파일명에 명단·선발자·합격자·대상자·인증자·당첨
  → 1차: 내려받지 않고 '보류' 행만 만든다 (글 제목에 걸리면 글도 열지 않는다)
받은 글에 학번형 숫자(19·20으로 시작하는 8~10자리)·휴대전화·주민등록번호 형식·가린 이름(홍*동)
  → 2차: '보류' (학교 업무 전화 032-870-…은 잡지 않는다)
글자를 읽지 못한 파일(그림·암호 HWP·아직 못 읽는 형식)
  → '보류' (검사하지 못한 것을 통과시키지 않는다)
교수진·직원 연락처·학생회·임원 페이지
  → 받되 '보류' (챗봇 답에 쓸지 아직 정하지 않았다)
```

보류 건은 사람이 확인 CSV에서 `통과`·`가림`·`제외`로 정한다. `제외`로 정하면 `import-review`가 원본 파일을 지우고 주소만 남긴다.
사람이 1차 보류를 `통과`로 바꾼 파일은 다음 수집 때 받고, 받은 내용에서 2차 패턴이 나오면 다시 확인 대기로 돌린다.

## 실행 (맥북)

```bash
cd tools/corpus
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                       # 네트워크 없이 합성 화면으로
.venv/bin/python -m corpus collect                   # 전체 수집(약 2.5시간, 이어 받기)
.venv/bin/python -m corpus collect --only faq,ipsi   # 일부만
.venv/bin/python -m corpus stats                     # 집계(형식·주제·개인정보·첨부 실측 크기)
.venv/bin/python -m corpus failures                  # 실패 목록
.venv/bin/python -m corpus export-review review.csv --unreviewed
.venv/bin/python -m corpus import-review review.csv
.venv/bin/python -m corpus add-file <파일> --doc-id ipsi/file/<이름> --site ipsi --topic 입시 --year 2026
.venv/bin/python -m corpus remeasure                 # 글을 읽지 못한 행을 원본으로 다시 재기(요청 없음)
```

`--root`를 주지 않으면 저장소의 `Assets/corpus/`를 쓴다. 대상은 `pages,regulations,faq,ipsi,depts,notices`.

## 챗봇에 올리기 (`upload`, 맥북에서 실행)

대장의 행을 챗봇 백엔드 API(화면 주소의 `/api`)로 올린다. 백엔드는 같은 파일(SHA-256)을 막고, 대장 정보
(대장 ID·원래 주소·게시일·학년도)와 카테고리를 AI 서버로 넘겨 청크 메타데이터에 넣는다.

| 대상(`--set`) | 고르는 행 | 올릴 곳 |
|---|---|---|
| `service` | `index_status='색인'`(지금 유효한 문서) | 서비스 챗봇 |
| `dataset` | `split='학습'`이고 개인정보 `통과` | 데이터셋용 색인(서비스와 다른 compose 프로젝트, 다른 주소) |

**준비**: 데스크탑이 켜져 있고 챗봇이 떠 있어야 한다(`docs/development/local-gpu/데스크탑-작업-시작-종료-절차.md`).
관리자 비밀번호를 알고 있어야 한다. 비밀번호는 실행할 때 직접 입력하고 어디에도 저장하지 않는다
(자동 실행이 필요하면 그때만 환경변수 `DOCUMIND_ADMIN_PASSWORD`에 넣는다).

```bash
cd tools/corpus
# 1) 무엇을 올릴지 확인만(요청 없음): 고른 행 수·형식별 수·파일 이름 다섯 개
.venv/bin/python -m corpus upload --base-url http://<챗봇 화면 주소> --set service --dry-run
# 2) 표본부터: 형식을 골라 몇 개만
.venv/bin/python -m corpus upload --base-url http://<챗봇 화면 주소> --set service --formats hwp,html --limit 10
# 3) 전체(한 문서씩 처리가 끝날 때까지 기다리며 올린다. 중간에 끊겨도 다시 실행하면 이어 올린다)
.venv/bin/python -m corpus upload --base-url http://<챗봇 화면 주소> --set service
# 4) 실패한 문서만 다시
.venv/bin/python -m corpus upload --base-url http://<챗봇 화면 주소> --set service --retry-failed
```

- 실행하면 대상·주소·고른 행 수를 보여 주고 `이 주소로 올릴까요? (y/N)`를 묻는다. 서비스와 데이터셋 주소를 헷갈리지 않게 꼭 확인한다.
- 처리 순서는 한 번에 한 문서다. 백엔드 문서 처리 실행기가 스레드 1개·대기열 20칸이라 연달아 보내면 거절된다.
- 결과는 `ledger.sqlite`의 `uploads` 표에 남는다: `ready`(올림) · `exists`(같은 파일이 이미 있음, 기존 문서 번호 기록) · `failed`(이유 기록).
  `service` 대상은 대장의 `uploaded_document_id`도 채운다.
- 실패가 **연속 5번**이면 멈춘다(서버가 꺼졌거나 로그인이 끊긴 경우). 원인을 고친 뒤 같은 명령을 다시 실행한다.
- 실패 이유가 "암호가 걸렸거나 배포용…"이면 한글에서 일반 문서나 PDF로 다시 저장해 관리자 화면으로 올린다.

결과 확인:

```bash
sqlite3 ../../Assets/corpus/ledger.sqlite "SELECT status, count(*) FROM uploads WHERE target='service' GROUP BY status"
sqlite3 ../../Assets/corpus/ledger.sqlite "SELECT doc_id, reason FROM uploads WHERE target='service' AND status='failed'"
```

## 결과물

```text
Assets/corpus/
├── ledger.sqlite      문서 대장 (ledger·failures·visits·uploads 테이블)
├── collect.log        수집 기록
└── raw/               원본: <사이트>/<종류>/<번호> (글 본문은 <글>/body.html, 첨부는 <글>/a<번호>.<확장자>)
```

대장 한 행은 파일 하나(안내 페이지 HTML, 글 본문, 첨부 각각)다. ID는 원래 주소에서 나온다
(`www/page/236`, `www/bbs/11/110588`, `www/bbs/11/110588/a162900`, `ipsi/viewer/13`, `www/faq/579/q<해시>`).
칸은 네 묶음이다.

| 묶음 | 칸 | 채움 |
|---|---|---|
| 출처 | `doc_id` `parent_id` `site` `kind` `board` `post_no` `url` `title` `posted_at` `collected_at` | 자동 |
| 파일 | `file_path` `format` `sha256` `size_bytes` `text_chars` `table_count` `image_heavy` | 자동 |
| 내용 판단 | `topic` `academic_year` `revised_at` `valid_until` `aliases` `group_id` `pii_status` `pii_reason` `third_party` | 자동 제안 → 사람 확인 |
| 용도 | `visibility` `index_status` `split` `uploaded_document_id` `reviewed` `notes` | 규칙·사람 |

사람이 확인한 행(`reviewed=1`)의 내용 판단 칸은 다시 수집해도 덮어쓰지 않는다. 값 목록은 `CHECK` 제약으로 막는다.
글자 수는 HTML은 BeautifulSoup, PDF는 pypdfium2, HWP는 olefile, HWPX는 zip 안 `Contents/sectionN.xml`의 `<hp:t>`에서 꺼낸 글 기준이다(공백을 하나로 줄임).
추출기를 고치거나 더하면 `remeasure`로 글을 읽지 못했던 행만 다시 잰다(사람이 확인한 행은 두고, 개인정보는 읽힌 글로 다시 판단).

## 평가셋 (`evalset`, 맥북에서 실행)

챗봇 시험지(평가셋)를 만드는 명령이다. 정본은 문항을 한 줄씩 쓴 JSONL 파일 하나(`Assets/eval/evalset.jsonl`, git 제외)다.
학교 글이 들어가므로 저장소에 올리지 않는다.

```text
export-index(색인 글, 데스크탑 켤 때) → Claude 초안 → check(기계 검사) → cross(교차 확인) → split(연습용·실전용)
  → need(사람이 꼭 볼 문항, 나머지 자동 승인) → review-html(검수 화면) → 사람 검수 → merge(검수 기록 합치기)
  → check(고친 문항 다시) → report(분포·검수 현황) → freeze(버전·SHA-256)
```

| 명령 | 하는 일 |
|---|---|
| `evalset export-index --base-url 주소 --index-backup 이름` | 서비스 색인의 청크 글을 문서별 파일로 받는다(`Assets/eval/index_text/<백업 이름>/`, 문서 번호·청크 수·SHA-256 기록). 데스크탑 챗봇이 떠 있어야 하고 관리자 비밀번호는 실행 때 입력 |
| `evalset check [파일] [--index-dir 폴더] [--write]` | 인용이 색인 글에 그대로 있나, 필수 사실이 인용 안에 있나, 근거 문서가 평가 몫·서비스 색인 문서인가, 같은 질문이 없나, 거절 문항에 부재 확인 기록이 있나, 지난해 판에 금지 값이 있나. 오류는 초안으로 돌려보내고 경고는 사람이 본다 |
| `evalset cross [파일] [--write]` | 교차 확인. 다른 Claude 세션(`claude -p`)이 정답지 없이 질문과 원본(HTML 원본·PDF 쪽 그림과 글자·HWP 글자)만 받아 풀고, 규칙 판정으로 정답지와 비교해 `cross`(일치·불일치·애매)를 채운다. 질문·명령·출력은 정본 옆 `cross/<시각>/`에 남는다. `--dry-run`은 꾸러미만 만들고, `--from-record 폴더`는 남긴 출력으로 다시 채운다 |
| `evalset fence` | 교차 확인 세션이 꾸러미 밖(가짜 정답지)을 못 읽는지 시험한다. 처음과 Claude Code 판이 바뀔 때 돌린다 |
| `evalset split [파일] --seed N [--write]` | 문서 묶음 단위로 연습용 60 : 실전용 40(주제마다). 문항이 10개를 넘는 묶음은 장(`evidence[0].section`) 단위 |
| `evalset need [파일] --seed N [--write]` | 교차 확인 불일치·경고·실전용 거절·표본 30을 사람에게, 나머지는 자동 승인. 표본에서 2개 이상 틀리면 `--more 30` |
| `evalset review-html [파일] [--index-dir 폴더]` | 사람이 꼭 볼 문항만 담은 검수 화면 HTML 파일 하나를 만든다(정본 옆 `review/`). 브라우저로 열고 서버·인터넷을 쓰지 않는다 |
| `evalset merge [파일] --records 기록.jsonl [--write]` | 검수 화면이 내려받은 검수 기록을 합친다. 고친 문항은 `rev`를 올리고 기계 검사를 비운다(다시 `check`). 같은 기록을 두 번 합쳐도 같다 |
| `evalset report [파일] [--cap 대장ID=수]` | 문항 수·답의 모양·주제·꼬리표·문서당 상한·검수 현황을 목표와 나란히 |
| `evalset freeze [파일] --version v1 --index-backup 이름 --seed N` | 사람이 볼 문항이 모두 판정됐고 버리지 않은 문항이 모두 기계 검사를 통과했는지 확인하고 고정 기록을 쓴다 |
| `evalset judge [파일] --id ev-0001 --answer "답"` | 규칙 판정(맞음·일부·모름·틀림·애매·빈 답)을 하나 해 본다 |

`check`는 `--index-dir`의 색인 글(챗봇이 보는 글)을 먼저 쓰고, 없으면 원본 파일을 이 도구의 추출기로 읽는다.
원본 추출(PDF는 pypdfium2, HWP는 olefile)은 서비스(OpenDataLoader·ai-server 로더)와 다른 읽기라서 교차 확인과 지난해 판 대조에 쓴다.

### 교차 확인 실행 (맥북 터미널)

`cross`와 `fence`는 Claude Code(`claude`)를 부른다. 맥북 터미널에서 `claude auth status`가 `"loggedIn": true`인지 먼저 본다.
확인하는 세션은 저장소 밖 임시 폴더의 꾸러미 안에서만 돈다. 명령에 붙는 설정과 이유:

| 설정 | 이유 |
|---|---|
| `--tools Read,Grep,Glob` | 읽기 도구만. 명령 실행·웹·파일 쓰기 없음 |
| `--restricted` | 파일 도구를 꾸러미 폴더 안에 가둔다. 사용자·프로젝트 설정 파일을 읽지 않는다 |
| `--safe-mode` | CLAUDE.md·스킬·출력 형식 같은 사용자 맞춤을 끈다(지시문만 받게) |
| `--permission-prompts none` | 허락을 물어야 하는 일은 모두 거절 |
| `--strict-mcp-config`, `--no-session-persistence` | 외부 도구 서버 없음, 대화를 남기지 않음 |

```bash
python -m corpus evalset fence
python -m corpus evalset cross --dry-run --keep-work
python -m corpus evalset cross --write
```

`fence`가 '실패'면 `cross`를 돌리지 않는다. 꾸러미가 저장소 안(`.git`·`CLAUDE.md`·`AGENTS.md`가 위에 있는 폴더)이면 `cross`가 거부한다.

## 테스트

`tests/fixtures/`의 화면은 학교 누리집(K2Web CMS)의 구조(클래스 이름·중첩)만 따른 **합성 화면**이다. 저장소가 공개라서
학교 화면을 그대로 넣지 않는다. 가짜 HTTP(`tests/conftest.py`)로 수집 전체 흐름을 네트워크 없이 시험한다. 평가셋 테스트는 지어낸 학교(가나대학) 데이터(`tests/evalset_data.py`)만 쓴다.

## 의존성 라이선스

| 패키지 | 라이선스 | 쓰임 |
|---|---|---|
| requests | Apache-2.0 | HTTP |
| beautifulsoup4 | MIT | HTML 해석 |
| olefile | BSD | HWP 5.0(OLE) 읽기 |
| pypdfium2 | Apache-2.0 / BSD-3-Clause (PDFium BSD-3-Clause) | PDF 글자 수, 교차 확인 쪽 그림·글자 |
| pillow | MIT-CMU | 교차 확인 PDF 쪽 그림 저장 |
| pytest (개발) | MIT | 테스트 |

HWP 5.0 글자 추출(`corpus/hwp.py`)은 한컴이 공개한 HWP 파일 형식 문서를 참고해 만들었다. 한컴의 사용 조건에 따라 아래 문구를 적는다.

> 본 제품은 한컴의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
