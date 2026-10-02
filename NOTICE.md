# 고지

## 한컴 HWP 문서 파일 형식

본 제품은 한컴의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.

HWP 5.0 문서를 읽는 코드(`ai-server/format_loaders/hwp5.py`, `tools/corpus/corpus/hwp.py`)는 한컴이 공개한
"HWP 문서 파일 형식" 문서를 참고해 만들었다. 한컴의 사용 조건은 개발 결과물의 화면·설명서·도움말·소스에 위 문구를
적도록 한다(https://www.hancom.com/etc/hwpDownload.do, "HWP 문서 파일 형식에 대한 사용권 및 저작권").
문구를 적은 곳: 관리자 화면의 문서 업로드 칸, 이 파일, `tools/corpus/README.md`, `tools/hwp-fixture/README.md`,
수집기 명령 도움말(`python -m corpus --help`), 위 두 소스 파일과 `ai-server/format_loaders/__init__.py`.

## 문서 형식 변환에 쓰는 라이브러리

| 라이브러리 | 라이선스 | 쓰임 |
|---|---|---|
| olefile 0.47 | BSD | HWP 5.0(OLE 복합 문서) 열기 |
| beautifulsoup4 4.15.0 | MIT | HTML 표 해석 |
| mammoth 1.11.0 | BSD-2-Clause | DOCX → HTML |
| markitdown 0.1.5 | MIT | 표 밖 HTML 글, PPTX·XLSX → 마크다운 |
| hwplib 1.1.9 (개발 도구만) | Apache-2.0 | 합성 HWP 시험 파일 만들기(`tools/hwp-fixture`). 서비스 코드에는 넣지 않는다 |
