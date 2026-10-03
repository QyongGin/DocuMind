"""생성·임베딩 모델 실행 설정 테스트.

예전에는 임베딩 요청도 생성 문맥(``OLLAMA_NUM_CTX``)을 그대로 써서, 생성 문맥을 늘리면
임베딩 모델도 같이 커졌다. 지금은 임베딩 문맥(``OLLAMA_EMBEDDING_NUM_CTX``)을 따로 쓰고,
생성 모델은 사고 모드를 끈다(Ollama ``think=false``).

Ollama 서버 없이 요청에 실리는 값만 확인한다.
"""

from __future__ import annotations

import main


class _FakeEmbedResponse:
    def model_dump(self) -> dict:
        return {"embeddings": [[0.0, 1.0]], "prompt_eval_count": 1}


class _RecordingOllamaClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def embed(self, **kwargs) -> _FakeEmbedResponse:
        self.calls.append(kwargs)
        return _FakeEmbedResponse()


def test_embedding_options_use_embedding_context_not_generation_context(monkeypatch):
    monkeypatch.setattr(main, "OLLAMA_NUM_CTX", 8192)
    monkeypatch.setattr(main, "OLLAMA_EMBEDDING_NUM_CTX", 2048)

    assert main._ollama_embedding_options()["num_ctx"] == 2048


def test_embed_request_carries_embedding_context(monkeypatch):
    recorder = _RecordingOllamaClient()
    monkeypatch.setattr(main, "ollama_client", recorder)
    monkeypatch.setattr(main, "OLLAMA_NUM_CTX", 8192)
    monkeypatch.setattr(main, "OLLAMA_EMBEDDING_NUM_CTX", 2048)

    main._embed_texts(["합성 청크"])

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["options"]["num_ctx"] == 2048


def test_generation_model_uses_generation_context_with_thinking_off():
    assert main.llm.num_ctx == main.OLLAMA_NUM_CTX
    assert main.llm.reasoning is False
