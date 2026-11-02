"""학습 예시의 그날과 그날 서비스 색인에 없었을 문서(ADR-0047). 가나대학 합성 대장으로.

질문 재료가 2025-08-13 공지면, 그날 뒤에 올라온 2026년 판은 늘 근거 후보에서 빠지고, 그날 이미 유효 기간이 지난
2024년 판은 약 90%의 예시에서 빠진다. 게시일이 없는 학과 페이지는 빠지지 않는다.
"""

from corpus.trainset import clients, pipeline, timeline

from test_trainset import FakeSession

MATERIAL = "gana/bbs/2025-2"  # 질문 재료: 2025-08-13 게시, 2025-08-31까지 유효
ROWS = [
    # (doc_id, parent_id, kind, posted_at, valid_until)
    (MATERIAL, None, "post", "2025-08-13", "2025-08-31"),
    ("gana/bbs/2025-1", None, "post", "2025-06-02", "2025-08-31"),  # 그날 유효
    ("gana/bbs/2026-2", None, "post", "2026-07-27", "2026-08-31"),  # 그날 뒤에 올라옴
    ("gana/bbs/2024-2", None, "post", "2024-10-21", "2025-02-28"),  # 그날 이미 만료
    ("gana/bbs/2024-2/a1", "gana/bbs/2024-2", "attach", None, None),  # 날짜 없는 첨부 → 부모 날짜
    ("gana/page/dept", None, "page", None, None),  # 게시일 없는 학과 페이지
    ("gana/bbs/not-uploaded", None, "post", "2027-01-01", "2027-02-28"),  # 데이터셋 색인에 없음
]


def make_ledger(ledger):
    for doc_id, parent_id, kind, posted_at, valid_until in ROWS:
        ledger.upsert({"doc_id": doc_id, "parent_id": parent_id, "site": "www", "kind": kind, "url": f"https://x/{doc_id}",
                       "title": f"가나대학 {doc_id}", "collected_at": "2026-10-02", "format": "html", "split": "학습",
                       "posted_at": posted_at, "valid_until": valid_until})
        if doc_id != "gana/bbs/not-uploaded":
            ledger.con.execute("INSERT INTO uploads VALUES ('dataset', ?, 's', 1, 'ready', NULL, 'http://x', '2026-10-21')",
                               (doc_id,))
    return timeline.ledger_dates(ledger.con)


def test_ledger_dates_cover_dataset_uploads_and_inherit_parent_dates(ledger):
    dates = make_ledger(ledger)
    assert "gana/bbs/not-uploaded" not in dates
    assert dates["gana/bbs/2024-2/a1"] == timeline.Dates("2024-10-21", "2025-02-28")
    assert dates["gana/page/dept"] == timeline.Dates(None, None)


def test_the_day_is_material_posting_date_or_today(ledger):
    dates = make_ledger(ledger)
    assert timeline.the_day(MATERIAL, dates, "2026-10-31") == "2025-08-13"
    assert timeline.the_day("gana/bbs/2024-2/a1", dates, "2026-10-31") == "2024-10-21"  # 첨부는 부모 게시일
    assert timeline.the_day("gana/page/dept", dates, "2026-10-31") == "2026-10-31"  # 게시일 없는 재료
    assert timeline.the_day(None, dates, "2026-10-31") == "2026-10-31"  # 재료 없는 예시


def test_excluded_documents_on_the_day(ledger):
    dates = make_ledger(ledger)
    assert timeline.excluded_ledger_ids("2025-08-13", dates) == ["gana/bbs/2024-2", "gana/bbs/2024-2/a1", "gana/bbs/2026-2"]
    # 옛 판을 남기는 예시는 그날 뒤 판만 뺀다
    assert timeline.excluded_ledger_ids("2025-08-13", dates, keep_old=True) == ["gana/bbs/2026-2"]


def test_old_versions_kept_in_about_one_tenth_of_examples_deterministically():
    ids = [f"r2-a-{number:04d}" for number in range(2000)]
    kept = [item_id for item_id in ids if timeline.keeps_old_versions(item_id)]
    assert 0.07 < len(kept) / len(ids) < 0.13
    assert kept == [item_id for item_id in ids if timeline.keeps_old_versions(item_id)]  # 다시 돌려도 같다


def test_attach_sends_exclusions_only_when_given():
    trace = {"answer_path": "llm", "prompt": "P", "stages": {"final": []}}
    plain = FakeSession({"answer": "답", "eval_trace": trace})
    clients.attach(plain, "http://ai", "질문")
    assert not {"exclude_ledger_ids", "exclude_chunk_ids", "as_of"} & set(plain.sent[0][1])  # 그 전 요청 그대로
    timed = FakeSession({"answer": "답", "eval_trace": trace})
    clients.attach(timed, "http://ai", "질문", exclude_ledger_ids=["gana/bbs/2026-2"], as_of="2025-08-13")
    assert timed.sent[0][1]["exclude_ledger_ids"] == ["gana/bbs/2026-2"] and timed.sent[0][1]["as_of"] == "2025-08-13"


def test_run_attach_uses_the_day_of_each_example(ledger, tmp_path):
    dates = make_ledger(ledger)
    batch = tmp_path / "r2"
    item = "r2-0002"  # 옛 판을 남기지 않는 예시 번호(아래에서 확인)
    assert not timeline.keeps_old_versions(item)
    pipeline.write(batch, "plan", [{"id": item, "kind": "fact", "ledger_id": MATERIAL, "chunks": []}], mode="w")
    pipeline.write(batch, "questions", [{"id": item, "question": "가나대학 국가근로 신청 언제까지야?", "possible": True}])
    session = FakeSession({"answer": "답", "eval_trace": {"answer_path": "llm", "prompt": "P", "stages": {"final": []}}})
    assert pipeline.run_attach(batch, session, "http://ai", dates=dates, today="2026-10-31", log=lambda line: None) == {
        "attached": 1}
    body = session.sent[0][1]
    assert body["as_of"] == "2025-08-13"
    assert body["exclude_ledger_ids"] == ["gana/bbs/2024-2", "gana/bbs/2024-2/a1", "gana/bbs/2026-2"]
    attached = pipeline.read(batch, "attached")[item]
    assert attached["timeline"] == {"as_of": "2025-08-13", "old_versions": False, "excluded_ledgers": 3}
