"""명령줄: `python -m corpus evalset <명령>`.

    check   기계 검사(인용 일치·사실 포함·문서 확인·중복·거절 기록·지난해 금지 값). --write면 결과를 정본에 쓴다
    split   개발용·확인용 나누기(문서 묶음 단위, 씨앗). --write면 정본에 쓴다
    need    사람이 꼭 볼 문항 고르기(불일치·경고·확인용 거절·표본), 나머지 자동 승인. --more N으로 표본 추가
    report  분포 보고(문항 수·모양·주제·꼬리표·문서당 상한·검수 현황)
    freeze  고정 기록(버전·SHA-256·문항 수) 쓰기
    judge   문항 하나에 답 하나를 규칙으로 판정해 보기
"""

import json
import sys
from datetime import date
from pathlib import Path

from ..ledger import Ledger
from . import checks, report, schema, split
from .judge import judge


def _ledger(args) -> Ledger:
    return Ledger(Path(args.root) / "ledger.sqlite")


def _today(args) -> date:
    return date.fromisoformat(args.today) if args.today else date.today()


def cmd_check(args) -> int:
    items = schema.load(args.file)
    ledger = _ledger(args)
    try:
        texts = checks.TextSource(ledger, args.root, args.index_dir)
        results = checks.check_all(items, ledger, texts, _today(args))
        failed = [item_id for item_id, result in results.items() if result["machine"]["errors"]]
        warned = [item_id for item_id, result in results.items()
                  if result["machine"]["warnings"] and not result["machine"]["errors"]]
        for item_id in failed:
            print(f"돌려보냄 {item_id}: {'; '.join(results[item_id]['machine']['errors'])}")
        for item_id in warned:
            print(f"경고 {item_id}: {'; '.join(results[item_id]['machine']['warnings'])}")
        print(f"문항 {len(items)} · 통과 {len(items) - len(failed)} · 돌려보냄 {len(failed)} · 경고 {len(warned)}")
        if args.write:
            checks.apply_results(items, results)
            schema.save(args.file, items)
        return 0 if not failed else 1
    finally:
        ledger.close()


def cmd_split(args) -> int:
    items = schema.load(args.file)
    ledger = _ledger(args)
    try:
        parts = split.assign_parts(items, ledger, args.seed, args.held)
    finally:
        ledger.close()
    for item in items:
        item["part"] = parts[item["id"]]
    main = [item for item in items if item["set"] == "본"]
    held = sum(1 for item in main if item["part"] == "확인")
    print(f"본 문항 {len(main)} · 개발 {len(main) - held} · 확인 {held} (씨앗 {args.seed})")
    if args.write:
        schema.save(args.file, items)
    return 0


def cmd_need(args) -> int:
    items = schema.load(args.file)
    if args.more:
        chosen = split.more_sample(items, args.seed, args.more)
        print(f"표본 {len(chosen)}개를 더 뽑았다: {', '.join(chosen)}")
    else:
        try:
            counts = split.choose_needs(items, args.seed, _today(args), args.sample)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(" · ".join(f"{need} {count}" for need, count in sorted(counts.items())))
    if args.write:
        schema.save(args.file, items)
    return 0


def cmd_report(args) -> int:
    caps = {}
    for entry in args.cap or []:
        doc, _, number = entry.rpartition("=")
        caps[doc] = int(number)
    ledger = _ledger(args)
    try:
        print("\n".join(report.build(schema.load(args.file), ledger, caps)))
    finally:
        ledger.close()
    return 0


def cmd_freeze(args) -> int:
    items = schema.load(args.file)
    try:
        text = split.freeze_text(items, args.version, args.index_backup, args.seed, _today(args))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else Path(args.file).with_name(f"frozen_{args.version}.txt")
    out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


def cmd_judge(args) -> int:
    item = next((entry for entry in schema.load(args.file) if entry["id"] == args.id), None)
    if item is None:
        print(f"문항이 없음: {args.id}", file=sys.stderr)
        return 1
    print(json.dumps(judge(item, args.answer, args.context), ensure_ascii=False))
    return 0


def add_parser(commands, default_file: Path) -> None:
    evalset = commands.add_parser("evalset", help="평가셋 정본 검사·나누기·꼭 볼 문항·고정")
    evalset.add_argument("--today", help="날짜 고정(YYYY-MM-DD, 시험용)")
    sub = evalset.add_subparsers(dest="evalset_command", required=True)

    def with_file(name: str, help_text: str):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("file", nargs="?", default=str(default_file), help=f"정본 파일(기본: {default_file})")
        return parser

    check = with_file("check", "기계 검사")
    check.add_argument("--index-dir", help="내보낸 색인 글 폴더. 없으면 원본 파일에서 뽑은 글로 대조")
    check.add_argument("--write", action="store_true", help="검사 결과를 정본에 쓴다")
    check.set_defaults(func=cmd_check)

    parts = with_file("split", "개발용·확인용 나누기")
    parts.add_argument("--seed", type=int, required=True)
    parts.add_argument("--held", type=float, default=split.HELD_RATIO, help="확인용 비율(기본 0.4)")
    parts.add_argument("--write", action="store_true")
    parts.set_defaults(func=cmd_split)

    need = with_file("need", "사람이 꼭 볼 문항 고르기")
    need.add_argument("--seed", type=int, required=True)
    need.add_argument("--sample", type=int, default=split.SAMPLE_SIZE, help="표본 수(기본 30)")
    need.add_argument("--more", type=int, help="표본을 이만큼 더 뽑는다(표본 오류가 2개 이상일 때)")
    need.add_argument("--write", action="store_true")
    need.set_defaults(func=cmd_need)

    summary = with_file("report", "분포 보고")
    summary.add_argument("--cap", action="append", help="문서당 상한 바꾸기: 대장ID=수 (여러 번 가능)")
    summary.set_defaults(func=cmd_report)

    freeze = with_file("freeze", "고정 기록 쓰기")
    freeze.add_argument("--version", required=True)
    freeze.add_argument("--index-backup", required=True, help="이 평가셋을 만든 색인의 백업 이름")
    freeze.add_argument("--seed", type=int, required=True, help="나누기에 쓴 씨앗")
    freeze.add_argument("--out", help="고정 기록 파일(기본: 정본 옆 frozen_<version>.txt)")
    freeze.set_defaults(func=cmd_freeze)

    trial = with_file("judge", "답 하나 판정해 보기")
    trial.add_argument("--id", required=True)
    trial.add_argument("--answer", required=True)
    trial.add_argument("--context", help="모델이 받은 근거 글(근거에 없는 숫자를 잡을 때)")
    trial.set_defaults(func=cmd_judge)
