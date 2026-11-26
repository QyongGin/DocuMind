# Development 문서

로컬 실행, 테스트, 개발환경 구축 문서를 둔다.

## 환경별 확정값 단일표 (다른 문서보다 이 표가 우선)

> 문서마다 포트·IP가 달라 혼선이 있었다(80 vs 19580). **진실은 각 환경의 `.env`이고, 이 표는 그 확인값이다.** 값이 바뀌면 이 표를 먼저 갱신한다. (Tailscale IP는 기기 재등록 시 변동 가능 — 사설망 주소이므로 공개 PR/issue에는 쓰지 않는다.)

| 항목 | 데스크탑 (실행 서버, 현행) | 맥북 로컬 (보조 검증) |
|---|---|---|
| 역할 | git pull + Docker **GPU** 스택 실행 (RTX 4070 Super, Windows 10 + WSL2) | 코드 작성·정적 검증·소형 smoke (CPU 전용, GPU passthrough 불가) |
| compose 명령 | `docker compose --project-name documind_desktop -f docker-compose.yml -f docker-compose.gpu.yml --env-file .env up -d --build` — **gpu.yml 필수, 빼면 CPU로 돈다** | `docker compose --project-name documind_local up -d --build` (대형 PDF 임베딩은 부적합) |
| FRONTEND_PORT | **19580** (데스크탑 .env에 설정) | 기본 **80** (.env.example 기준) |
| SSH 접속 | 맥북에서 `ssh desktop` (= `<사용자>@<WSL IP>`, WSL/Ubuntu 노드. `~/.ssh/config` 별칭, keepalive 포함) | — |
| 브라우저 테스트 | 맥북에서 `ssh -N -L 19580:127.0.0.1:19580 desktop-win`을 연 뒤 `http://localhost:19580`(2026-11-09부터. WSL 주소로는 큰 응답이 멈추고 Windows 주소는 로그인·질문이 403, `알려진-문제.md`) | `http://127.0.0.1:80` |
| 외부 시연 | `ssh -t desktop 'cloudflared tunnel --url http://localhost:19580'` → trycloudflare 임시 URL | — |
| 금지 | `docker compose down -v`, `git reset --hard`, GCP | 동일 |

코드 반영 루프(맥북 push → SSH → 데스크탑 pull → compose up)는 루트 `AGENTS.md` §3. 실제 주소(`<WSL IP>`·`<Windows IP>`·`<사용자>`)는 로컬 전용 `docs/local/접속정보.md`.

| 문서 | 역할 |
|---|---|
| `local-gpu/데스크탑-작업-시작-종료-절차.md` | 데스크탑은 작업할 때만 켠다(2026-09-30~). 켜기·확인·끄기 순서 |
| `알려진-문제.md` | 아직 고치지 않은 동작과 피해 가는 방법(데스크탑·WSL, Docker·저장소, 평가·측정, GitHub) |
| `local-gpu/평가-실행-절차.md` | 데스크탑에서 평가셋 실행, 채점, 짝 비교 |
| `local-gpu/데이터셋-색인-절차.md` | 학습 예시용 데이터셋 색인 스택 띄우기 |

DB·색인 백업·복원은 `docs/deployment/DB-색인-백업-복원-절차.md`. 지난 환경 문서(로컬 GPU 구축 가이드 2026-06, 원격 접속 정의서, 맥북 단독 테스트, API 수동 테스트)는 `docs/archive/development/`에 있다(로컬 전용).
