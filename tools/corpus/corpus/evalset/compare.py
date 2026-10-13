"""두 실행의 짝 비교(ADR-0025): 같은 평가셋 판으로 채점한 두 결과 폴더를 같은 문항끼리 짝 지어 지표마다 비교한다.

지표마다 문항별로 예/아니오를 정하고, A만 예인 문항 수(b)와 B만 예인 문항 수(c)로 정확 이항 검정(매크니마 검정)을 한다.
양측 p < 0.05면 '의미 있는 차이', 아니면 '같은 수준'. 둘 다 예이거나 둘 다 아니오인 문항은 차이에 쓰지 않는다.

- 두 결과 모두 같은 평가셋(지문)으로 채점했어야 한다. 실행 때 판과 다른 판으로 다시 채점한 결과도 된다(score-run --rescore)
- 애매가 남은 결과는 비교하지 않는다 — 판정을 먼저 채운다
- 두 쪽 모두 채점된 문항만 짝 짓는다(미실행·실패·질문 바뀜은 빼고 수만 센다)
- 기본은 개발셋만 본다. 테스트셋은 정해진 때(13번 모델 비교·M2 끝)에만 --part로 넣고, 합계만 낸다(ADR-0018).
  결과가 갈린 문항 ID는 개발셋 문항만 돌려준다
"""

import json
import math
from pathlib import Path

from . import schema
from .metrics import DEV_RESULTS, METRICS, TEST_RESULTS

ALPHA = 0.05
PARTS = {"dev": ("dev",), "test": ("test",), "all": ("dev", "test")}
# (이름, 문항 묶음, 문항별 '예', 낮을수록 좋은가)
METRIC_RULES = (
    ("정답률", lambda row: row["shape"] != "답없음", lambda row: row["label"] == "맞음", False),
    ("환각률", lambda row: True, lambda row: row["label"] == "틀림", True),
    ("과잉 거절률", lambda row: row["shape"] != "답없음", lambda row: row["label"] == "모름", True),
    ("출처 정확도", lambda row: row["shape"] != "답없음", lambda row: bool(row.get("source_any")), False),
    ("답없음 거절", lambda row: row["shape"] == "답없음", lambda row: row["label"] == "맞음", False),
    ("안내 충실도", lambda row: row.get("guidance") not in (None, "해당 없음"), lambda row: row["guidance"] == "충족", False),
)


def mcnemar_exact(b: int, c: int) -> float:
    """정확 이항 검정의 양측 p: 결과가 갈린 b + c 문항이 반반으로 갈린다는 가정에서 지금보다 치우칠 확률."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def scored_fingerprint(result_dir: Path) -> str:
    """결과 폴더를 채점한 평가셋 지문. 다시 채점한 결과는 scored_with, 실행 폴더에서 채점한 결과는 실행 기록의 지문."""
    metrics = json.loads((result_dir / METRICS).read_text(encoding="utf-8"))
    return (metrics.get("scored_with") or {}).get("evalset_sha256") or metrics["manifest"]["evalset_sha256"]


def load_rows(result_dir: Path, parts: tuple[str, ...]) -> dict[str, dict]:
    names = {"dev": DEV_RESULTS, "test": TEST_RESULTS}
    rows = {}
    for part in parts:
        for line in (result_dir / names[part]).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["id"]] = row
    return rows


def compare(evalset_path: str | Path, dir_a: str | Path, dir_b: str | Path, part: str = "dev") -> dict:
    """두 결과 폴더의 짝 비교. 돌려주는 것: 문항 묶음(본·쉬운)마다 지표별 A·B 비율, b·c·p·판정."""
    dir_a, dir_b = Path(dir_a), Path(dir_b)
    fingerprint = schema.fingerprint(schema.load(evalset_path))
    for result_dir in (dir_a, dir_b):
        if scored_fingerprint(result_dir) != fingerprint:
            raise ValueError(f"{result_dir}: 이 평가셋 파일로 채점한 결과가 아니다 — 같은 판으로 채점(score-run --rescore)한 뒤 비교한다")
    rows_a, rows_b = load_rows(dir_a, PARTS[part]), load_rows(dir_b, PARTS[part])
    for name, rows in (("A", rows_a), ("B", rows_b)):
        open_ = sum(1 for row in rows.values() if row.get("status") == "채점" and row["label"] == "애매")
        if open_:
            raise ValueError(f"{name}에 애매가 {open_}개 남아 있다 — 판정을 채우고 다시 채점한 뒤 비교한다")
    paired = [(rows_a[item_id], rows_b[item_id]) for item_id in sorted(rows_a.keys() & rows_b.keys())
              if rows_a[item_id].get("status") == "채점" and rows_b[item_id].get("status") == "채점"]
    result = {"evalset_sha256": fingerprint, "part": part, "a": str(dir_a), "b": str(dir_b),
              "unpaired": len(rows_a.keys() | rows_b.keys()) - len(paired), "sets": {}}
    for set_name in ("본", "쉬운"):
        pairs = [(a, b) for a, b in paired if a["set"] == set_name]
        if pairs:
            result["sets"][set_name] = {name: _metric(pairs, scope, yes, lower_better)
                                        for name, scope, yes, lower_better in METRIC_RULES}
    return result


def _metric(pairs: list[tuple[dict, dict]], scope, yes, lower_better: bool) -> dict:
    chosen = [(a, b) for a, b in pairs if scope(a)]
    only_a = [a for a, b in chosen if yes(a) and not yes(b)]
    only_b = [a for a, b in chosen if yes(b) and not yes(a)]
    p = mcnemar_exact(len(only_a), len(only_b))
    return {"n": len(chosen), "a_yes": sum(1 for a, _ in chosen if yes(a)), "b_yes": sum(1 for _, b in chosen if yes(b)),
            "only_a": len(only_a), "only_b": len(only_b), "p": round(p, 4),
            "verdict": "의미 있는 차이" if p < ALPHA else "같은 수준", "lower_better": lower_better,
            # 결과가 갈린 문항 ID는 개발셋만 돌려준다(테스트셋 봉인, ADR-0018)
            "dev_only_a": [row["id"] for row in only_a if row.get("part") == "dev"],
            "dev_only_b": [row["id"] for row in only_b if row.get("part") == "dev"]}


def summary_lines(result: dict) -> list[str]:
    """화면용 요약. 문항 ID는 넣지 않는다(개발셋 ID는 --out 파일에)."""

    def pct(k, n):
        return f"{k / n * 100:.1f}% ({k}/{n})" if n else "—"

    lines = [f"짝 비교({result['part']}): A {result['a']} · B {result['b']} · 짝 못 지은 문항 {result['unpaired']}"]
    for set_name, metrics in result["sets"].items():
        lines.append(f"[{set_name}]")
        for name, entry in metrics.items():
            if not entry["n"]:
                continue  # 이 묶음에 해당 문항이 없다(쉬운 문항의 답없음 등)
            better = ""
            if entry["verdict"] == "의미 있는 차이":
                b_higher = entry["only_b"] > entry["only_a"]
                better = " → B가 나음" if b_higher != entry["lower_better"] else " → A가 나음"
            lines.append(f"  {name}{'(낮을수록 좋음)' if entry['lower_better'] else ''}: A {pct(entry['a_yes'], entry['n'])}"
                         f" · B {pct(entry['b_yes'], entry['n'])} · A만 {entry['only_a']} · B만 {entry['only_b']}"
                         f" · p {entry['p']} · {entry['verdict']}{better}")
    return lines
