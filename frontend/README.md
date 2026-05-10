# DocuMind Frontend

React 19 + Vite 기반 DocuMind 사용자/관리자 화면이다. Docker 배포에서는 nginx가 정적 파일을 서빙하고 `/api` 요청을 Spring Boot backend로 reverse proxy한다.

## 실행

```bash
npm install
npm run dev
```

로컬 Vite 개발 서버는 `vite.config.js`에서 `/api`를 `http://localhost:8080`으로 프록시한다.

## 환경변수

`.env.example`을 기준으로 로컬 `.env`를 만들 수 있다. `.env`는 git 커밋 대상이 아니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` | Spring Boot API reverse proxy 기준 URL |
| `VITE_DEFAULT_TOP_K` | `3` | SSE 질의응답 검색 문서 수 기본값 |

## 구조

```text
src/
├── components/
│   ├── common/        # 공통 UI 조각
│   └── layout/        # 앱 공통 레이아웃
├── config/            # Vite 환경변수 정규화
├── features/
│   ├── admin/         # 관리자 로그인/대시보드
│   ├── chat/          # 사용자 질의응답 화면
│   └── not-found/     # 404 화면
├── services/          # API, 인증 토큰, SSE 클라이언트
└── utils/             # 세션키 등 순수 유틸
```

## 라우트

| 경로 | 화면 |
|---|---|
| `/` | 사용자 질의응답 |
| `/admin/login` | 관리자 로그인 |
| `/admin` | 관리자 대시보드 기본 골격 |

## 검증

```bash
npm run lint
npm run build
```
