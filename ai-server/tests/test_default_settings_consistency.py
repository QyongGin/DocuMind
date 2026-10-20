"""운영 기본값이 여러 파일에 나뉘어 있어도 같은 값인지 확인한다(M2 2단계, 2026-10-15).

검색 개수(상위 k)는 백엔드·프론트·AI 서버가 각자 기본값을 갖는다. 백엔드가 AI 서버에 늘 값을 보내므로
한 곳만 바뀌면 화면·백엔드·AI 서버가 서로 다른 개수로 동작한다. 생성 문맥도 compose·환경 예시·AI 서버에 있다.
모델 이름은 AI 서버·compose·환경 예시와 데스크탑 모델 준비 단계(ADR-0036)에 있다. 준비 단계만 다른 이름이면
AI 서버가 등록되지 않은 모델을 부른다.
"""
import re
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def env_example(name: str) -> int:
    return int(re.search(rf"^{name}=(\d+)$", read(".env.example"), re.M).group(1))


def compose_default(name: str) -> int:
    return int(re.search(rf"\$\{{{name}:-(\d+)\}}", read("docker-compose.yml")).group(1))


def env_example_text(name: str) -> str:
    return re.search(rf"^{name}=(\S+)$", read(".env.example"), re.M).group(1)


def compose_text_defaults(path: str, name: str) -> list[str]:
    # 같은 파일에 같은 기본값이 여러 번 나오면 모두 본다
    return re.findall(rf"\$\{{{name}:-([^}}]+)\}}", read(path))


def main_py_default(name: str) -> str:
    # 실행 환경의 환경값과 무관하게 코드에 적힌 기본값을 읽는다
    return re.search(rf'os\.getenv\("{name}", "([^"]+)"\)', read("ai-server/main.py")).group(1)


def test_default_top_k_is_the_same_everywhere():
    values = {
        "ai-server main.py": main.DEFAULT_TOP_K,
        ".env.example CHAT": env_example("CHAT_DEFAULT_TOP_K"),
        ".env.example AI": env_example("AI_DEFAULT_TOP_K"),
        ".env.example VITE": env_example("VITE_DEFAULT_TOP_K"),
        "compose CHAT": compose_default("CHAT_DEFAULT_TOP_K"),
        "compose AI": compose_default("AI_DEFAULT_TOP_K"),
        "compose VITE": compose_default("VITE_DEFAULT_TOP_K"),
        "backend application.yaml": int(re.search(r"\$\{CHAT_DEFAULT_TOP_K:(\d+)\}", read("backend/src/main/resources/application.yaml")).group(1)),
        "frontend Dockerfile": int(re.search(r"ARG VITE_DEFAULT_TOP_K=(\d+)", read("frontend/Dockerfile")).group(1)),
        "frontend env.js 기본": int(re.search(r"VITE_DEFAULT_TOP_K \?\? '(\d+)'", read("frontend/src/config/env.js")).group(1)),
        "frontend env.js 잘못된 값일 때": int(re.search(r"parsedTopK : (\d+),", read("frontend/src/config/env.js")).group(1)),
    }
    assert len(set(values.values())) == 1, values


def test_generation_context_is_the_same_everywhere():
    values = {"ai-server main.py": main.OLLAMA_NUM_CTX, ".env.example": env_example("OLLAMA_NUM_CTX"),
              "compose": compose_default("OLLAMA_NUM_CTX")}
    assert len(set(values.values())) == 1, values


def test_rerank_candidates_default_is_the_same_everywhere():
    # 재순위 후보 수(M2 3단계 ③에서 고른 20개)는 AI 서버·compose·환경 예시에 있다
    values = {
        "ai-server main.py": main.RERANK_CANDIDATES,
        ".env.example": env_example("AI_RERANK_CANDIDATES"),
        "compose": compose_default("AI_RERANK_CANDIDATES"),
    }
    assert len(set(values.values())) == 1, values


def test_model_names_are_the_same_everywhere():
    for name in ("OLLAMA_LLM_MODEL", "OLLAMA_EMBEDDING_MODEL"):
        compose = compose_text_defaults("docker-compose.yml", name)
        gpu = compose_text_defaults("docker-compose.gpu.yml", name)
        assert compose and gpu, (name, compose, gpu)
        values = {"ai-server main.py": main_py_default(name), ".env.example": env_example_text(name)}
        values.update({f"compose {i}": v for i, v in enumerate(compose)})
        values.update({f"compose gpu {i}": v for i, v in enumerate(gpu)})
        assert len(set(values.values())) == 1, (name, values)
