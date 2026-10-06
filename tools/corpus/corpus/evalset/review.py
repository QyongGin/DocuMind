"""검수 화면(결정 ④·⑦)과 검수 기록 합치기.

- 검수 화면: 사람이 꼭 볼 문항(`need`가 있는 문항)만 담은 HTML 파일 하나. 맥북 브라우저로 열고 서버·인터넷을 쓰지 않는다.
  근거 원문(색인 글, 없으면 원본에서 뽑은 글)을 앞뒤 글과 함께 보여 주고 인용 줄에 색을 칠한다.
- 검수 기록: 화면이 내려받게 하는 JSONL(문항 ID·판정·이유·고친 칸·걸린 초). `merge`가 정본에 합친다.
  고침은 고친 칸을 바꾸고 `rev`를 올리며 기계 검사 결과를 비운다(다시 `check`). 같은 기록을 두 번 합쳐도 결과가 같다.
"""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..ledger import Ledger
from . import schema
from .checks import TextSource, quote_key

TEMPLATE = Path(__file__).with_name("review_template.html")
FULL_LIMIT = 12_000  # 이보다 짧은 문서는 전체를 보여 준다
WINDOW = 2_500  # 긴 문서는 인용 앞뒤로 이만큼
EDITABLE = ("question", "answer", "shape", "tags", "facts", "forbidden")
RECORD_STATUSES = ("승인", "고침", "버림", "보류")
DROP_REASONS = ("근거불일치", "답여럿", "바뀌지않는값", "개인정보", "중복", "시점지남", "기타")


def quote_span(text: str, quote: str) -> tuple[int, int] | None:
    """인용이 있는 글자 범위. 기계 검사(`quote_key`)처럼 공백과 표 구분선(`|`)은 무시하고 찾는다."""
    key = quote_key(quote)
    if not key:
        return None
    positions, chars = [], []
    for index, char in enumerate(text):
        for normalized in unicodedata.normalize("NFKC", char):
            if normalized.isspace() or normalized == "|":
                continue
            positions.append(index)
            chars.append(normalized)
    at = "".join(chars).find(key)
    if at < 0:
        return None
    return positions[at], positions[at + len(key) - 1] + 1


def window(text: str, spans: list[tuple[int, int]]) -> tuple[int, str]:
    """(시작 위치, 보여 줄 글). 짧은 문서는 전체, 긴 문서는 인용 앞뒤 `WINDOW`자를 줄 경계에 맞춰 자른다."""
    if len(text) <= FULL_LIMIT:
        return 0, text
    if not spans:
        end = text.rfind("\n", 0, FULL_LIMIT)
        return 0, text[:end if end > 0 else FULL_LIMIT]
    start = max(0, min(span[0] for span in spans) - WINDOW)
    end = min(len(text), max(span[1] for span in spans) + WINDOW)
    start = text.rfind("\n", 0, start) + 1 if start > 0 else 0
    newline = text.find("\n", end)
    end = newline if newline != -1 else len(text)
    return start, text[start:end]


def need_why(item: dict) -> str:
    need = item.get("need")
    cross = item.get("cross") or {}
    if need == "불일치":
        return f"교차 확인 답: {cross.get('answer') or '(없음)'} — 규칙 판정 '{cross.get('label') or cross.get('verdict')}'"
    if need == "경고":
        return "; ".join((item.get("machine") or {}).get("warnings") or []) or "기계 검사 경고"
    if need == "실전용 거절":
        return "실전용 거절 문항은 모두 사람이 확인"
    if need == "표본":
        return "실전용 자동 승인 문항 중 무작위 표본"
    return ""


def _source(texts: TextSource, ledger: Ledger, doc_id: str, quotes: list[str], where: str | None) -> dict:
    row = ledger.get(doc_id) or {}
    text = texts.get(doc_id)
    if text is None:
        return {"doc": doc_id, "title": row.get("title") or doc_id, "url": row.get("url"), "where": where,
                "text": None, "offset": 0, "spans": [], "length": 0}
    spans = [span for span in (quote_span(text, quote) for quote in quotes) if span]
    offset, shown = window(text, spans)
    return {"doc": doc_id, "title": row.get("title") or doc_id, "url": row.get("url"), "where": where,
            "text": shown, "offset": offset, "length": len(text),
            "spans": [[start - offset, end - offset] for start, end in spans if offset <= start and end <= offset + len(shown)]}


def entry(item: dict, texts: TextSource, ledger: Ledger) -> dict:
    """검수 화면에 넣을 문항 하나."""
    data = {key: item.get(key) for key in ("id", "rev", "part", "need", "set", "shape", "tags", "topic", "question",
                                           "answer", "facts", "forbidden", "year", "refusal", "review", "note")}
    data["why"] = need_why(item)
    cross = item.get("cross") or {}
    data["cross"] = {key: cross.get(key) for key in ("answer", "quote", "where", "verdict", "label", "reader", "model")}
    data["warnings"] = (item.get("machine") or {}).get("warnings") or []
    sources = []
    if item["shape"] == "거절":
        near = (item.get("refusal") or {}).get("near")
        if near:
            sources.append(_source(texts, ledger, near, [], "가까운 문서"))
    else:
        by_doc: dict[str, list[dict]] = {}
        for evidence in item["evidence"]:
            by_doc.setdefault(evidence["doc"], []).append(evidence)
        for doc_id, entries in by_doc.items():
            sources.append(_source(texts, ledger, doc_id, [evidence["quote"] for evidence in entries],
                                   " · ".join(evidence.get("where") or "" for evidence in entries).strip(" ·") or None))
    data["sources"] = sources
    return data


def build_html(items: list[dict], texts: TextSource, ledger: Ledger, built_at: datetime, source_name: str) -> tuple[str, int]:
    """(HTML, 담은 문항 수). 사람이 볼 이유(`need`)가 있는 문항만 담는다(이미 판정한 문항도 다시 볼 수 있게 담는다)."""
    chosen = [item for item in sorted(items, key=lambda entry_: entry_["id"]) if item.get("need")]
    payload = {
        "built_at": built_at.isoformat(timespec="seconds"),
        "source": source_name,
        "total": len(items),
        "auto": sum(1 for item in items if (item.get("review") or {}).get("status") == "자동 승인"),
        "shapes": list(schema.SHAPES), "tags": list(schema.TAGS), "forbid_why": list(schema.FORBID_WHY),
        "drop_reasons": list(DROP_REASONS),
        "items": [entry(item, texts, ledger) for item in chosen],
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)
    return html, len(chosen)


def load_records(paths: list[str | Path]) -> list[dict]:
    records = []
    for path in paths:
        for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{number}: JSON으로 읽을 수 없음 ({error.msg})") from error
    return records


def merge(items: list[dict], records: list[dict]) -> dict:
    """검수 기록을 정본에 합친다. 문항마다 가장 늦은 기록만 쓴다. 돌려주는 것: {"counts": Counter, "errors": [...]}."""
    by_id = {item["id"]: item for item in items}
    latest: dict[str, dict] = {}
    for record in records:
        item_id = record.get("id")
        if not isinstance(item_id, str):
            continue
        if item_id not in latest or str(record.get("at") or "") >= str(latest[item_id].get("at") or ""):
            latest[item_id] = record
    counts: Counter = Counter()
    errors: list[str] = []
    for item_id, record in sorted(latest.items()):
        item = by_id.get(item_id)
        status = record.get("status")
        if item is None:
            errors.append(f"정본에 없는 문항: {item_id}")
            continue
        if status not in RECORD_STATUSES:
            errors.append(f"{item_id}: 판정 값이 목록에 없음({status})")
            continue
        review = item.get("review") or {}
        if review.get("status") == status and review.get("at") == record.get("at"):
            counts["이미 합침"] += 1
            continue
        if status == "고침":
            edits = record.get("edits") or {}
            unknown = [key for key in edits if key not in EDITABLE]
            if not edits or unknown:
                errors.append(f"{item_id}: 고친 칸이 없거나 고칠 수 없는 칸({', '.join(unknown) or '없음'})")
                continue
            problems = schema.validate({**item, **edits})
            if problems:
                errors.append(f"{item_id}: 고친 내용이 형식에 맞지 않음 — {'; '.join(problems)}")
                continue
            item.update(edits)
            item["rev"] = int(item.get("rev") or 1) + 1
            item["machine"] = None  # 고친 문항은 기계 검사를 다시 한다(정본 형식 §3)
        item["review"] = {"status": status, "reason": str(record.get("reason") or ""), "at": record.get("at"),
                          "sec": int(record.get("sec") or 0)}
        if record.get("changed"):
            item["review"]["changed"] = list(record["changed"])
        counts[status] += 1
    return {"counts": counts, "errors": errors}
