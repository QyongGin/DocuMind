"""기계 검사(결정 ④·⑦): 사람이 보기 전에 정본 문항을 자동으로 거른다.

오류(`errors`)가 있는 문항은 초안으로 돌려보내고, 경고(`warnings`)가 있는 문항은 사람이 꼭 본다.
문서 글은 내보낸 색인 글(`Assets/eval/index_text/`)을 먼저 쓰고, 없으면 원본 파일에서 뽑은 글을 쓴다.
"""

import re
import unicodedata
from datetime import date
from pathlib import Path

from .. import extract
from ..ledger import Ledger
from . import schema
from .judge import contains, normalize

EXCLUDE_NOTE = "[평가질문제외]"
MIN_TEXT_CHARS = 100
_YEAR_SUFFIX = re.compile(r"(.*:)(\d{4})$")


def index_text_name(doc_id: str) -> str:
    """대장 ID를 파일 이름으로: `www/bbs/11/1` → `www__bbs__11__1.txt`."""
    return doc_id.replace("/", "__") + ".txt"


def quote_key(text: str) -> str:
    """인용 대조용 글: 전각만 맞추고 공백과 표 구분선(`|`)은 뺀다. 숫자·날짜 표기는 바꾸지 않는다(글자 그대로)."""
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", str(text)))


class TextSource:
    """문서 글을 읽는다. `index_dir`의 색인 글이 있으면 그것을(챗봇이 보는 글), 없으면 원본 파일을 corpus 추출기로."""

    def __init__(self, ledger: Ledger, corpus_root: str | Path, index_dir: str | Path | None = None):
        self.ledger = ledger
        self.corpus_root = Path(corpus_root)
        self.index_dir = Path(index_dir) if index_dir else None
        self._cache: dict[tuple[str, bool], str | None] = {}

    def get(self, doc_id: str) -> str | None:
        return self._read(doc_id, prefer_index=True)

    def raw(self, doc_id: str) -> str | None:
        """원본 파일에서 뽑은 글(서비스 파이프라인과 다른 읽기). 교차 확인·지난해 판 대조에 쓴다."""
        return self._read(doc_id, prefer_index=False)

    def _read(self, doc_id: str, prefer_index: bool) -> str | None:
        key = (doc_id, prefer_index)
        if key not in self._cache:
            text = None
            if prefer_index and self.index_dir is not None:
                path = self.index_dir / index_text_name(doc_id)
                if path.exists():
                    text = path.read_text(encoding="utf-8")
            if text is None:
                text = self._extract(doc_id)
            self._cache[key] = text
        return self._cache[key]

    def _extract(self, doc_id: str) -> str | None:
        row = self.ledger.get(doc_id)
        if not row or not row.get("file_path"):
            return None
        path = self.corpus_root / row["file_path"]
        if not path.exists():
            return None
        fmt = row["format"]
        if fmt == "html":
            return extract.html_metrics(path.read_text(encoding="utf-8", errors="replace"))[3]
        if fmt == "pdf":
            return extract.pdf_metrics(str(path))[2]
        if fmt == "hwp":
            return extract.hwp_metrics(str(path))[2]
        if fmt == "hwpx":
            return extract.hwpx_metrics(str(path))[2]
        return None


def previous_year_doc(ledger: Ledger, doc_id: str) -> str | None:
    """같은 문서 묶음의 지난해 판. 묶음 이름이 `…:2027`이면 `…:2026` 묶음에서 파일이 있는 행을 찾는다."""
    row = ledger.get(doc_id)
    match = _YEAR_SUFFIX.match((row or {}).get("group_id") or "")
    if not match:
        return None
    previous = f"{match.group(1)}{int(match.group(2)) - 1}"
    found = ledger.con.execute(
        "SELECT doc_id FROM ledger WHERE group_id = ? AND file_path IS NOT NULL ORDER BY doc_id LIMIT 1",
        (previous,)).fetchone()
    return found[0] if found else None


def question_key(question: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", question)).lower()


def _doc_errors(item: dict, row: dict | None, near: bool = False) -> list[str]:
    """근거 문서(또는 거절 문항의 가까운 문서)가 평가 문항에 쓸 수 있는 문서인가."""
    if row is None:
        return ["근거 문서가 대장에 없음"]
    errors = []
    if item["split"] == "평가" and row.get("split") != "평가":
        errors.append("근거 문서가 평가 몫이 아님")
    if row.get("index_status") != "색인":
        errors.append("근거 문서가 서비스 색인 문서가 아님")
    if EXCLUDE_NOTE in (row.get("notes") or ""):
        errors.append("평가 질문에서 뺀 문서([평가질문제외])")
    if row.get("kind") != "faq" and (row.get("text_chars") or 0) < MIN_TEXT_CHARS:
        errors.append(f"글이 {MIN_TEXT_CHARS}자 미만인 문서")
    if not near and item["set"] == "본" and row.get("kind") == "faq" and "다른 말" not in item["tags"]:
        errors.append("FAQ를 근거로 한 본 문항은 '다른 말' 꼬리표가 있어야 함")
    return errors


def check_item(item: dict, ledger: Ledger, texts: TextSource) -> dict:
    """문항 하나의 기계 검사 결과(`machine` 칸)와 대장에서 가져온 `topic`·`valid_until`."""
    errors = schema.validate(item)
    warnings: list[str] = []
    result = {"quote_ok": None, "facts_in_quote": None, "doc_ok": None, "values_ok": not errors,
              "dup_of": None, "refusal_ok": None, "prev_year_ok": None}
    fill: dict = {}
    if errors:
        result.update(errors=errors, warnings=warnings)
        return {"machine": result, "fill": fill}

    if item["shape"] == "거절":
        refusal = item["refusal"]
        check = refusal.get("check")
        if not check:
            errors.append("부재 확인 기록이 없음")
            result["refusal_ok"] = False
        else:
            result["refusal_ok"] = True
            if check["hits"] > 0:
                warnings.append(f"부재 확인에 걸린 글 {check['hits']}건 — 답이 있는지 사람이 봄")
        if refusal.get("near"):
            row = ledger.get(refusal["near"])
            errors.extend(f"가까운 문서: {message}" for message in _doc_errors(item, row, near=True))
            if row:
                fill.update(topic=row.get("topic"), valid_until=row.get("valid_until"))
    else:
        primary = item["evidence"][0]["doc"]
        row = ledger.get(primary)
        doc_errors = _doc_errors(item, row)
        result["doc_ok"] = not doc_errors
        errors.extend(doc_errors)
        if row:
            fill.update(topic=row.get("topic"), valid_until=row.get("valid_until"))
        quote_ok = True
        for entry in item["evidence"]:
            text = texts.get(entry["doc"])
            if text is None:
                errors.append(f"근거 문서 글을 읽지 못함: {entry['doc']}")
                quote_ok = False
            elif quote_key(entry["quote"]) not in quote_key(text):
                errors.append(f"인용이 원문에 없음: {entry['doc']}")
                quote_ok = False
        result["quote_ok"] = quote_ok
        if item["shape"] != "설명":
            quotes = normalize(" ".join(entry["quote"] for entry in item["evidence"]))
            absent = [fact["name"] for fact in item["facts"]
                      if not any(contains(quotes, value) for value in fact["values"])]
            result["facts_in_quote"] = not absent
            errors.extend(f"필수 사실이 인용에 없음: {name}" for name in absent)
        for doc_id in item.get("also") or []:
            also_row = ledger.get(doc_id)
            if not also_row or also_row.get("index_status") != "색인":
                errors.append(f"허용 근거가 서비스 색인 문서가 아님: {doc_id}")
        last_year_values = [entry["value"] for entry in item["forbidden"] if entry["why"] == "지난해 값"]
        if "연도 시험" in item["tags"] and last_year_values:
            previous = previous_year_doc(ledger, primary)
            previous_text = texts.raw(previous) if previous else None
            if previous_text is None:
                warnings.append("지난해 판 원문을 찾지 못해 금지 값을 대조하지 못함")
                result["prev_year_ok"] = None
            else:
                normalized_previous = normalize(previous_text)
                absent = [value for value in last_year_values if not contains(normalized_previous, value)]
                result["prev_year_ok"] = not absent
                warnings.extend(f"금지 값이 지난해 판에 없음: {value}" for value in absent)
    result.update(errors=errors, warnings=warnings)
    return {"machine": result, "fill": fill}


def check_all(items: list[dict], ledger: Ledger, texts: TextSource, today: date) -> dict:
    """모든 문항을 검사하고 `{문항 ID: {machine, fill}}`을 돌려준다. 같은 질문은 뒤의 문항을 오류로 본다."""
    results = {item["id"]: check_item(item, ledger, texts) for item in items}
    seen: dict[str, str] = {}
    for item in sorted(items, key=lambda entry: entry["id"]):
        key = question_key(str(item.get("question", "")))
        if not key:
            continue
        if key in seen:
            machine = results[item["id"]]["machine"]
            machine["dup_of"] = seen[key]
            machine["errors"].append(f"같은 질문이 이미 있음: {seen[key]}")
        else:
            seen[key] = item["id"]
    for result in results.values():
        result["machine"]["at"] = today.isoformat()
    return results


def apply_results(items: list[dict], results: dict) -> None:
    for item in items:
        result = results[item["id"]]
        item["machine"] = result["machine"]
        for key, value in result["fill"].items():
            if value is not None:
                item[key] = value
