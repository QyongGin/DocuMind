"""평가셋 테스트용 지어낸 학교(가나대학) 데이터: 대장 행, 원본 파일, 정본 문항.

저장소가 공개라서 실제 학교 문서는 넣지 않는다.
"""

from pathlib import Path

from pdfgen import make_pdf

FEE_HTML = """<h2>전형료 안내</h2>
<table><tr><th>구분</th><th>수시 1차</th><th>정시</th></tr>
<tr><td>전형료</td><td>30,000원</td><td>30,000원</td></tr>
<tr><td>실기 추가</td><td>15,000원</td><td>-</td></tr></table>
<p>원서 접수: 2026. 9. 8.(월) ~ 9. 19.(금)</p>"""

FEE_HTML_2026 = """<h2>전형료 안내</h2>
<table><tr><th>구분</th><th>수시 1차</th></tr><tr><td>전형료</td><td>25,000원</td></tr></table>"""

LEAVE_HTML = """<h2>휴학 신청</h2>
<p>휴학은 학기 시작 전부터 수업일수 4분의 1이 지나기 전까지 신청할 수 있습니다.</p>
<p>제출 서류: 휴학원서 1부, 보호자 동의서 1부 (입대 휴학은 입영통지서 사본을 더 냅니다)</p>"""

FAQ_HTML = """<h1>등록금 환불</h1><p>포털에서 등록금 환불 신청서를 제출하면 재무팀 확인 후 본인 명의 계좌로 환불됩니다.</p>"""

DORM_HTML = """<h2>생활관 안내</h2><p>생활관 식비: 학기당 650,000원(1일 2식). 기숙사비와 함께 냅니다.</p>"""

TINY_HTML = "<p>준비 중</p>"


def ledger_row(doc_id: str, **extra) -> dict:
    base = {"doc_id": doc_id, "site": "gana", "kind": "page", "url": f"https://gana.example/{doc_id}",
            "title": doc_id, "collected_at": "2026-10-02", "format": "html", "topic": "입시",
            "split": "평가", "index_status": "색인", "text_chars": 500, "pii_status": "통과"}
    base.update(extra)
    return base


def build_corpus(ledger, root: Path) -> None:
    """대장 행과 원본 파일을 만든다. 평가 몫 5개, 학습 몫 1개(생활관), 지난해 판 1개(보관)."""
    files = {
        "gana/page/fee": ("raw/gana/page/fee.html", FEE_HTML, {"group_id": "모집요강:신입생:2027", "academic_year": 2027}),
        "gana/page/fee2026": ("raw/gana/page/fee2026.html", FEE_HTML_2026,
                              {"group_id": "모집요강:신입생:2026", "split": "학습", "index_status": "보관",
                               "academic_year": 2026}),
        "gana/page/leave": ("raw/gana/page/leave.html", LEAVE_HTML, {"topic": "학사", "group_id": "안내:휴학"}),
        "gana/faq/refund": ("raw/gana/faq/refund.html", FAQ_HTML,
                            {"topic": "장학·등록금", "kind": "faq", "text_chars": 60, "group_id": "FAQ:환불"}),
        "gana/page/dorm": ("raw/gana/page/dorm.html", DORM_HTML,
                           {"topic": "학과·캠퍼스 생활", "split": "학습", "group_id": "안내:생활관"}),
        "gana/page/tiny": ("raw/gana/page/tiny.html", TINY_HTML, {"text_chars": 5, "group_id": "안내:빈"}),
        "gana/page/excluded": ("raw/gana/page/excluded.html", LEAVE_HTML,
                               {"topic": "학사", "notes": "[평가질문제외] 학습 문서와 글 90% 이상 같음",
                                "group_id": "안내:제외"}),
    }
    for doc_id, (relpath, html, extra) in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        ledger.upsert(ledger_row(doc_id, file_path=relpath, **extra))
    pdf = root / "raw/gana/viewer/guide.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(make_pdf(["Guide 2027", "Fee 30000"]))
    ledger.upsert(ledger_row("gana/viewer/guide", format="pdf", file_path="raw/gana/viewer/guide.pdf",
                             group_id="모집요강:안내서:2027"))


def item(item_id: str, **extra) -> dict:
    """답 있는 '값' 문항 하나(전형료). 필요한 칸만 바꿔 쓴다."""
    base = {
        "id": item_id, "rev": 1, "set": "본", "split": "평가", "part": None,
        "question": "가나대 원서비 얼마예요?", "shape": "값", "tags": ["표 근거", "다른 말", "연도 시험"],
        "topic": None, "answer": "2027학년도 전형료는 30,000원입니다.",
        "facts": [{"name": "전형료", "values": ["30,000원", "3만 원"]}],
        "forbidden": [{"value": "25,000원", "why": "지난해 값"}],
        "evidence": [{"doc": "gana/page/fee", "quote": "전형료 30,000원", "where": "전형료 표"}],
        "also": [], "year": 2027, "valid_until": None, "refusal": None,
        "made_by": "claude-opus-5-5", "made_at": "2026-10-05",
    }
    base.update(extra)
    return base


def refusal_item(item_id: str, **extra) -> dict:
    base = item(item_id, question="가나대 2028학년도 정원 몇 명이에요?", shape="거절", tags=["연도 시험"],
                answer="2028학년도 정원은 문서에서 확인할 수 없습니다.", facts=[],
                forbidden=[{"value": "40명", "why": "지어낼 법한 값"}], evidence=[], year=2028,
                refusal={"kind": "가까운 빈칸", "near": "gana/page/fee",
                         "check": {"terms": ["2028", "정원"], "hits": 0, "hit_docs": [], "at": "2026-10-05",
                                   "index": "20261004-201713", "trace": False}})
    base.update(extra)
    return base
