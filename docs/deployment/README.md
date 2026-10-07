# deployment 문서 인덱스

현행 실행 환경은 데스크탑 로컬 GPU 스택이다. 환경값은 `docs/development/README.md`, 켜고 끄는 절차는 `docs/development/local-gpu/데스크탑-작업-시작-종료-절차.md`.

| 문서 | 역할 |
|---|---|
| `DB-색인-백업-복원-절차.md` | MySQL·Chroma 백업(`deploy/backup.sh`)과 복원(`deploy/restore.sh`), 복원 리허설 방법과 기록 (2026-09-30, M0-7) |

학교 서버 배포·운영 문서는 M4·M6에서 이 폴더에 만든다. 과거 Docker·GCP 배포 문서는 `docs/archive/deployment/`에 있다(로컬 전용, 그대로 실행하지 않는다).
