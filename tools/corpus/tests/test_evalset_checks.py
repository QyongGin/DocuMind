"""정본 형식 검증과 기계 검사(결정 ④·⑦): 인용 일치, 사실 포함, 문서 확인, 중복, 거절 기록, 지난해 금지 값."""

from datetime import date

import pytest
from evalset_data import build_corpus, item, refusal_item

from corpus.evalset import checks, schema

TODAY = date(2026, 10, 5)


@pytest.fixture
def corpus(ledger, tmp_path):
    build_corpus(ledger, tmp_path)
    return ledger, checks.TextSource(ledger, tmp_path)


def run(items, corpus):
    ledger, texts = corpus
    return checks.check_all(items, ledger, texts, TODAY)


def test_schema_rejects_bad_values_and_round_trips(tmp_path):
    good = item("ev-0001")
    assert schema.validate(good) == []
    assert any("shape" in error for error in schema.validate(item("ev-0002", shape="표")))
    assert any("ID" in error for error in schema.validate(item("x-1")))
    assert any("쉬운" in error for error in schema.validate(item("ev-0003", set="쉬운")))
    assert any("금지 값" in error for error in schema.validate(item("ev-0004", forbidden=[{"value": "1", "why": "그냥"}])))
    assert any("거절 문항" in error for error in schema.validate(refusal_item("ev-0005", refusal=None)))
    path = tmp_path / "evalset.jsonl"
    schema.save(path, [item("ev-0002"), good])
    loaded = schema.load(path)
    assert [entry["id"] for entry in loaded] == ["ev-0001", "ev-0002"]
    assert schema.fingerprint(loaded) == schema.fingerprint([dict(reversed(list(good.items()))), item("ev-0002")])


def test_good_item_passes_and_gets_topic(corpus):
    result = run([item("ev-0001")], corpus)["ev-0001"]
    machine = result["machine"]
    assert machine["errors"] == [] and machine["warnings"] == []
    assert (machine["quote_ok"], machine["facts_in_quote"], machine["doc_ok"], machine["prev_year_ok"]) == (True, True, True, True)
    assert result["fill"]["topic"] == "입시"


def test_quote_and_fact_mismatches_go_back_to_draft(corpus):
    results = run([
        item("ev-0001", evidence=[{"doc": "gana/page/fee", "quote": "전형료 31,000원"}]),
        item("ev-0002", question="실기 추가 비용은?", evidence=[{"doc": "gana/page/fee", "quote": "실기 추가 15,000원"}],
             tags=["표 근거"], forbidden=[]),
    ], corpus)
    assert any("인용이 원문에 없음" in error for error in results["ev-0001"]["machine"]["errors"])
    assert any("필수 사실이 인용에 없음: 전형료" in error for error in results["ev-0002"]["machine"]["errors"])


@pytest.mark.parametrize(("doc", "message"), [
    ("gana/page/dorm", "평가 몫이 아님"),
    ("gana/page/excluded", "[평가질문제외]"),
    ("gana/page/tiny", "100자 미만"),
    ("gana/page/none", "대장에 없음"),
])
def test_documents_that_cannot_be_evidence(corpus, doc, message):
    errors = run([item("ev-0001", evidence=[{"doc": doc, "quote": "x"}])], corpus)["ev-0001"]["machine"]["errors"]
    assert any(message in error for error in errors)


def test_faq_evidence_needs_rephrased_question(corpus):
    faq = {"doc": "gana/faq/refund", "quote": "재무팀 확인 후 본인 명의 계좌로 환불됩니다"}
    base = dict(question="등록금 돌려받으려면?", shape="절차", forbidden=[], evidence=[faq],
                facts=[{"name": "확인", "values": ["재무팀"]}])
    plain = run([item("ev-0001", tags=["글 근거"], **base)], corpus)["ev-0001"]["machine"]["errors"]
    rephrased = run([item("ev-0002", tags=["글 근거", "다른 말"], **base)], corpus)["ev-0002"]["machine"]["errors"]
    easy = run([item("ev-0003", set="쉬운", tags=["FAQ 제목", "글 근거"], **base)], corpus)["ev-0003"]["machine"]["errors"]
    assert any("다른 말" in error for error in plain)
    assert rephrased == [] and easy == []  # FAQ 문서는 글이 짧아도 쓸 수 있다


def test_duplicate_questions_keep_the_first(corpus):
    results = run([item("ev-0001"), item("ev-0002", question="가나대 원서비, 얼마예요")], corpus)
    assert results["ev-0001"]["machine"]["dup_of"] is None
    assert results["ev-0002"]["machine"]["dup_of"] == "ev-0001"


def test_refusal_records(corpus):
    missing = refusal_item("ev-0001", question="학식 메뉴는요?", refusal={"kind": "자료 없음", "near": None})
    hit = refusal_item("ev-0002", question="기숙사 식비는요?", refusal={
        "kind": "자료 없음", "near": None, "check": {"terms": ["식비"], "hits": 1, "hit_docs": ["gana/page/dorm"]}})
    far = refusal_item("ev-0003", question="생활관 정원은요?", refusal={
        "kind": "가까운 빈칸", "near": "gana/page/dorm", "check": {"terms": ["정원"], "hits": 0}})
    results = run([missing, hit, far, refusal_item("ev-0004")], corpus)
    assert "부재 확인 기록이 없음" in results["ev-0001"]["machine"]["errors"]
    assert results["ev-0002"]["machine"]["errors"] == [] and results["ev-0002"]["machine"]["warnings"]
    assert any("가까운 문서" in error for error in results["ev-0003"]["machine"]["errors"])
    assert results["ev-0004"]["machine"]["errors"] == [] and results["ev-0004"]["fill"]["topic"] == "입시"


def test_last_year_value_must_exist_in_last_year_document(corpus):
    unknown = item("ev-0001", forbidden=[{"value": "27,000원", "why": "지난해 값"}])
    result = run([unknown], corpus)["ev-0001"]["machine"]
    assert result["prev_year_ok"] is False
    assert any("지난해 판에 없음" in warning for warning in result["warnings"])


def test_exported_index_text_wins_over_raw_file(ledger, tmp_path):
    build_corpus(ledger, tmp_path)
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / checks.index_text_name("gana/page/fee")).write_text("| 전형료 | 32,000원 |", encoding="utf-8")
    texts = checks.TextSource(ledger, tmp_path, index_dir)
    good = item("ev-0001", evidence=[{"doc": "gana/page/fee", "quote": "전형료 | 32,000원"}],
                facts=[{"name": "전형료", "values": ["32,000원"]}])
    assert checks.check_all([good], ledger, texts, TODAY)["ev-0001"]["machine"]["errors"] == []
    assert "30,000원" in texts.raw("gana/page/fee")  # 교차 확인·지난해 판 대조는 원본에서 뽑은 글


def test_pdf_raw_text(corpus):
    pdf_item = item("ev-0001", question="Guide fee?", tags=["글 근거"], forbidden=[],
                    evidence=[{"doc": "gana/viewer/guide", "quote": "Fee 30000"}],
                    facts=[{"name": "fee", "values": ["30000"]}])
    assert run([pdf_item], corpus)["ev-0001"]["machine"]["errors"] == []
