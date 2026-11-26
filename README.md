# DocuMind

인하공업전문대학 홈페이지 문서에 근거해 답하는 RAG(검색 증강 생성) 챗봇입니다. 학생, 교직원, 지원자처럼 학교에 궁금한 것이 있는 사람이 질문하면, 학교 문서에서 찾은 근거로 결론과 안내, 참고한 문서를 보여 줍니다.

## 구성

| 경로 | 역할 |
|---|---|
| `frontend/` | 사용자 화면(React 19, Vite) |
| `backend/` | REST API, 인증, 채팅 기록, 문서 관리(Spring Boot, Java, MySQL) |
| `ai-server/` | 문서 파싱, 청킹, 색인, 검색, 답변 생성(FastAPI, ChromaDB, Ollama) |
| `tools/` | 학교 문서 수집과 문서 대장, 평가셋, 학습 데이터 도구 |
| `deploy/` | 모델 변환과 등록, DB와 색인 백업·복원 스크립트 |

## 실행

환경값과 compose 명령은 [docs/development/README.md](docs/development/README.md)에 있습니다. GPU 서버에서는 `docker-compose.gpu.yml`을 함께 올립니다.

## 문서

- 문서 지도: [docs/README.md](docs/README.md)
- 지금 진행 중인 단계: [docs/rag/m2/README.md](docs/rag/m2/README.md)
- 설계 결정: [docs/adr/README.md](docs/adr/README.md)
- 협업 규칙(브랜치, 커밋, PR): [CONTRIBUTING.md](CONTRIBUTING.md)
