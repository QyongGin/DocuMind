"""질문 임베딩이 앞 요청과 무관하게 같은 계산 경로를 타는지 확인한다.

Ollama는 바로 앞 입력과 같은 글이나 앞부분이 겹치는 글을 받으면 앞 계산(입력 캐시)을 다시 써서 벡터가 조금 달라진다.
질문을 임베딩하기 전에 앞부분이 겹칠 수 있으면 첫 글자가 다른 짧은 글을 먼저 보내 캐시를 비운다.
Ollama 서버 없이 보낸 요청의 순서만 본다(가나대학 합성 질문).
"""

from __future__ import annotations

import pytest

import main


class _FakeEmbedResponse:
    def __init__(self, texts: list[str]) -> None:
        self._texts = texts

    def model_dump(self) -> dict:
        return {"embeddings": [[float(len(text)), float(ord(text[0]))] for text in self._texts], "prompt_eval_count": 1}


class _RecordingOllamaClient:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    def embed(self, **kwargs) -> _FakeEmbedResponse:
        self.inputs.append(list(kwargs["input"]))
        return _FakeEmbedResponse(list(kwargs["input"]))


@pytest.fixture
def recorder(monkeypatch):
    client = _RecordingOllamaClient()
    monkeypatch.setattr(main, "ollama_client", client)
    monkeypatch.setattr(main, "_last_embedded_text", None)
    return client


def _is_reset(request: list[str]) -> bool:
    return len(request) == 1 and request[0] in main.EMBEDDING_CACHE_RESET_TEXTS


def test_first_query_resets_cache_and_returns_question_vector(recorder):
    vectors, _ = main._embed_query("가나대학 휴학은 어떻게 신청해요?")

    assert len(recorder.inputs) == 2
    assert _is_reset(recorder.inputs[0])
    assert recorder.inputs[1] == ["가나대학 휴학은 어떻게 신청해요?"]
    assert vectors == [[float(len("가나대학 휴학은 어떻게 신청해요?")), float(ord("가"))]]


def test_same_question_again_resets_cache_first(recorder):
    main._embed_query("도서관은 몇 시에 닫아요?")
    recorder.inputs.clear()

    main._embed_query("도서관은 몇 시에 닫아요?")

    assert len(recorder.inputs) == 2
    assert _is_reset(recorder.inputs[0])


def test_question_with_different_first_letter_skips_reset(recorder):
    main._embed_query("도서관은 몇 시에 닫아요?")
    recorder.inputs.clear()

    main._embed_query("기숙사 신청 기간은 언제예요?")

    assert recorder.inputs == [["기숙사 신청 기간은 언제예요?"]]


def test_question_sharing_first_letter_resets(recorder):
    main._embed_query("휴학은 어떤 종류가 있어요?")
    recorder.inputs.clear()

    main._embed_query("휴학은 온라인으로 어떻게 신청해요?")

    assert len(recorder.inputs) == 2
    assert _is_reset(recorder.inputs[0])


def test_batch_embedding_makes_next_query_reset(recorder):
    main._embed_query("도서관은 몇 시에 닫아요?")
    main._embed_texts(["가나대학 학칙 제1조", "기숙사 안내 청크"])
    recorder.inputs.clear()

    main._embed_query("셔틀버스는 어디서 타요?")

    assert len(recorder.inputs) == 2
    assert _is_reset(recorder.inputs[0])


def test_reset_text_never_starts_like_the_question(recorder):
    question = main.EMBEDDING_CACHE_RESET_TEXTS[0] + " 표시가 붙은 항목은 뭐예요?"

    main._embed_query(question)

    assert _is_reset(recorder.inputs[0])
    assert recorder.inputs[0][0][:1] != question[:1]
