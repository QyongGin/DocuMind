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
| 평일 9~18시(한국 시간)에는 요청하지 않는다 | 이 시간에 요청하려 하면 멈춘다(`Stop`). 다음 실행이 이어 받는다 |
| User-Agent에 프로젝트 이름 | `DocuMind-corpus-collector/0.1 (...)`, 이메일은 넣지 않는다 |
| 403·429·5xx가 이어지면 간격을 두 배로, 5번 연속이면 멈춘다 | `PoliteSession.get` (간격 상한 30초) |
| 이어 받기 | 끝까지 처리한 단위(페이지·글·FAQ 게시판)를 `visits`에 적고 다음 실행에서 건너뛴다. 실패가 있었던 단위는 다시 시도한다 |
| 같은 내용은 한 번만 | SHA256이 같은 파일은 새로 쓰지 않고 먼저 받은 파일을 가리키며, 비고에 `내용 중복`을 적고 색인에서 뺀다 |
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
```

`--root`를 주지 않으면 저장소의 `Assets/corpus/`를 쓴다. 대상은 `pages,regulations,faq,ipsi,depts,notices`.

## 결과물

```text
Assets/corpus/
├── ledger.sqlite      문서 대장 (ledger·failures·visits 테이블)
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
글자 수는 HTML은 BeautifulSoup, PDF는 pypdfium2, HWP는 olefile로 꺼낸 글 기준이다(공백을 하나로 줄임).

## 테스트

`tests/fixtures/`의 화면은 학교 누리집(K2Web CMS)의 구조(클래스 이름·중첩)만 따른 **합성 화면**이다. 저장소가 공개라서
학교 화면을 그대로 넣지 않는다. 가짜 HTTP(`tests/conftest.py`)로 수집 전체 흐름을 네트워크 없이 시험한다.

## 의존성 라이선스

| 패키지 | 라이선스 | 쓰임 |
|---|---|---|
| requests | Apache-2.0 | HTTP |
| beautifulsoup4 | MIT | HTML 해석 |
| olefile | BSD | HWP 5.0(OLE) 읽기 |
| pypdfium2 | Apache-2.0 / BSD-3-Clause (PDFium BSD-3-Clause) | PDF 글자 수 |
| pytest (개발) | MIT | 테스트 |
