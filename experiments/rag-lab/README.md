# DocuMind RAG Lab

DocuMind 본 서비스를 포팅하지 않고, 기존 `ai-server`를 호출해 RAG 답변과 Markdown 표 렌더링을 확인하는 Python 실험용 웹이다.

## 실행

1. 기존 AI 서버를 먼저 실행한다.

```bash
cd ai-server
source venv/bin/activate
uvicorn main:app --reload
```

2. 다른 터미널에서 RAG Lab을 실행한다.

```bash
cd experiments/rag-lab
python3 app.py
```

3. 브라우저에서 `http://127.0.0.1:7860`에 접속한다.

## 환경변수

| 이름 | 기본값 | 설명 |
|---|---:|---|
| `RAG_LAB_AI_BASE_URL` | `http://localhost:8000` | 호출할 DocuMind AI 서버 주소 |
| `RAG_LAB_HOST` | `127.0.0.1` | 실험 웹 바인딩 호스트 |
| `RAG_LAB_PORT` | `7860` | 실험 웹 포트 |
| `RAG_LAB_REQUEST_TIMEOUT` | `180` | AI 서버 요청 타임아웃 초 |

학교 서버나 Docker 내부 AI 서버를 보려면 예를 들어 다음처럼 실행한다.

```bash
RAG_LAB_AI_BASE_URL=http://192.168.35.168:8000 python3 app.py
```

## 확인할 수 있는 것

- `/query` 답변이 Markdown 표를 포함할 때 HTML 표로 렌더링되는지 확인한다.
- 같은 답변의 Markdown 원문을 함께 확인한다.
- `/debug/rag-trace` 결과에서 vector, BM25, table_fact, evidence focus 후보를 확인한다.
- 출처 문서, 페이지, 청크, 섹션 정보를 본 서비스와 분리해서 점검한다.

## 범위

이 실험 웹은 로그인, 관리자, 문서 업로드, 채팅 이력 저장을 구현하지 않는다. RAG 답변 품질과 Markdown 표 출력 검증만 빠르게 하기 위한 도구이다.
