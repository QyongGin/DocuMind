"""근거 꼬리표가 서버를 띄울 때마다 바뀌지 않는지(해시 씨앗과 무관한지) 확인한다.

질문 단어는 집합(set)에 담기고, 집합의 순회 순서는 PYTHONHASHSEED마다 다르다. 길이가 같은 단어가 둘 이상
줄에 들어 있을 때 꼬리표가 씨앗과 무관하게 같아야 같은 설정 재실행끼리 프롬프트가 같다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

AI_SERVER = Path(__file__).resolve().parents[1]

SCRIPT = """
from types import SimpleNamespace
import main
terms = {"휴학신청", "복학신청", "전과신청", "수강신청", "졸업신청", "장학신청"}
line = "휴학신청 복학신청 전과신청 수강신청 졸업신청 장학신청 안내"
analysis = SimpleNamespace(primary_terms=terms, subject_terms=set(terms))
print(main._extract_item_label(line, analysis))
print("|".join(main._by_length_desc(terms | {"신청", "학사 일정 안내"})))
"""


def _run(seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    out = subprocess.run([sys.executable, "-c", SCRIPT], cwd=AI_SERVER, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip().splitlines()[-2:]


def test_item_label_is_the_same_for_every_hash_seed():
    results = {tuple(_run(seed)) for seed in ("0", "1", "2", "3", "4", "5")}
    assert len(results) == 1, results
    label, order = next(iter(results))
    # 길이가 같으면 글자순 첫 단어, 순서는 긴 단어부터
    assert label == min({"휴학신청", "복학신청", "전과신청", "수강신청", "졸업신청", "장학신청"})
    assert order.split("|")[0] == "학사 일정 안내" and order.split("|")[-1] == "신청"
