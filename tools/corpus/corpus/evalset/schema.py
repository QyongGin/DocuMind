"""평가셋 정본 형식: 문항 한 줄(JSONL)의 칸과 값 목록, 읽기·쓰기·검증, 지문.

평가 몫과 학습 몫(M2)이 같은 형식을 쓰고 `split`으로 나눈다. 칸 정의를 바꾸면 기계 검사·검수 화면·채점기가
모두 이 모듈을 따라간다.
"""

import hashlib
import json
import re
from pathlib import Path

SETS = ("본", "쉬운")
SPLITS = ("평가", "학습")
PARTS = ("개발", "확인")
SHAPES = ("값", "목록", "절차", "예아니오", "설명", "거절")
TAGS = ("표 근거", "글 근거", "해마다 바뀜", "연도 시험", "다른 말", "FAQ 제목", "조건", "비교·계산", "여러 근거")
REFUSAL_KINDS = ("가까운 빈칸", "잘못된 전제", "자료 없음", "무관")
FORBID_WHY = ("지난해 값", "옆 칸 값", "다른 학과 값", "지어낼 법한 값")
STATUSES = ("승인", "고침", "버림", "보류", "자동 승인")
NEEDS = ("불일치", "경고", "확인용 거절", "표본")
CROSS_VERDICTS = ("일치", "불일치", "애매")
ID_RE = re.compile(r"(ev|tr)-\d{4,}")
REQUIRED = ("id", "rev", "set", "split", "question", "shape", "tags", "answer", "facts", "forbidden",
            "evidence", "made_by", "made_at")


def load(path: str | Path) -> list[dict]:
    items = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{number}: JSON으로 읽을 수 없음 ({error.msg})") from error
    return items


def save(path: str | Path, items: list[dict]) -> None:
    """ID 순으로 한 줄씩 쓴다. 중간에 끊겨도 원래 파일이 남도록 임시 파일에 쓰고 바꾼다."""
    path = Path(path)
    lines = [json.dumps(item, ensure_ascii=False) for item in sorted(items, key=lambda item: item["id"])]
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    temporary.replace(path)


def fingerprint(items: list[dict]) -> str:
    """칸 순서·줄 순서와 상관없이 같은 내용이면 같은 SHA-256."""
    canonical = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for item in sorted(items, key=lambda item: item["id"])
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(text, str) and text.strip() for text in value)


def validate(item: dict) -> list[str]:
    """형식 오류 목록. 빈 목록이면 형식은 맞다(내용이 맞는지는 기계 검사·사람이 본다)."""
    missing = [key for key in REQUIRED if key not in item]
    if missing:
        return [f"빠진 칸: {', '.join(missing)}"]
    errors = []
    if not ID_RE.fullmatch(str(item["id"])):
        errors.append(f"문항 ID 형식이 아님: {item['id']}")
    for key, allowed in (("set", SETS), ("split", SPLITS), ("shape", SHAPES)):
        if item[key] not in allowed:
            errors.append(f"{key} 값이 목록에 없음: {item[key]}")
    if item.get("part") not in (None, *PARTS):
        errors.append(f"part 값이 목록에 없음: {item.get('part')}")
    if not isinstance(item["tags"], list) or any(tag not in TAGS for tag in item["tags"]):
        errors.append(f"꼬리표가 목록에 없음: {item['tags']}")
    if not str(item["question"]).strip():
        errors.append("질문이 비었음")
    if not str(item["answer"]).strip():
        errors.append("정답 문장이 비었음")
    if not isinstance(item["facts"], list) or not all(
            isinstance(fact, dict) and str(fact.get("name", "")).strip() and _strings(fact.get("values")) and fact["values"]
            for fact in item["facts"]):
        errors.append("필수 사실은 이름과 허용 표기(하나 이상)가 있어야 함")
    if not isinstance(item["forbidden"], list) or not all(
            isinstance(entry, dict) and str(entry.get("value", "")).strip() and entry.get("why") in FORBID_WHY
            for entry in item["forbidden"]):
        errors.append(f"금지 값은 값과 이유({'·'.join(FORBID_WHY)})가 있어야 함")
    if not isinstance(item["evidence"], list) or not all(
            isinstance(entry, dict) and str(entry.get("doc", "")).strip() and str(entry.get("quote", "")).strip()
            for entry in item["evidence"]):
        errors.append("근거는 문서 ID와 인용 글이 있어야 함")
    if item["shape"] == "거절":
        refusal = item.get("refusal")
        if item["facts"] or item["evidence"]:
            errors.append("거절 문항은 필수 사실·근거가 없어야 함")
        if not isinstance(refusal, dict) or refusal.get("kind") not in REFUSAL_KINDS:
            errors.append(f"거절 문항은 refusal.kind({'·'.join(REFUSAL_KINDS)})가 있어야 함")
        else:
            check = refusal.get("check")
            if check is not None and (not _strings(check.get("terms")) or not check.get("terms")
                                      or not isinstance(check.get("hits"), int) or check["hits"] < 0):
                errors.append("부재 확인 기록은 찾은 낱말과 걸린 수가 있어야 함")
    else:
        if not item["facts"]:
            errors.append("답 있는 문항은 필수 사실이 하나 이상 있어야 함")
        if not item["evidence"]:
            errors.append("답 있는 문항은 근거가 하나 이상 있어야 함")
        if item.get("refusal"):
            errors.append("거절 문항이 아닌데 refusal이 있음")
    if item["set"] == "쉬운" and "FAQ 제목" not in item["tags"]:
        errors.append("쉬운 문항은 'FAQ 제목' 꼬리표가 있어야 함")
    review = item.get("review")
    if review is not None and (not isinstance(review, dict) or review.get("status") not in STATUSES):
        errors.append(f"검수 상태가 목록에 없음: {review}")
    if item.get("need") not in (None, *NEEDS):
        errors.append(f"need 값이 목록에 없음: {item.get('need')}")
    cross = item.get("cross")
    if cross is not None and (not isinstance(cross, dict) or cross.get("verdict") not in CROSS_VERDICTS):
        errors.append(f"교차 확인 결과가 목록에 없음: {cross}")
    return errors
