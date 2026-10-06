"""명령줄: `python -m corpus evalset <명령>`.

    export-index  서비스 색인의 청크 글을 문서별 파일로 받기(데스크탑 챗봇이 떠 있어야 함)
    check         기계 검사(인용 일치·사실 포함·문서 확인·중복·거절 기록·지난해 금지 값). --write면 결과를 정본에 쓴다
    cross         교차 확인: 다른 Claude 세션이 정답지 없이 다른 읽기로 풀고 규칙 판정으로 비교
    fence         교차 확인 세션이 꾸러미 밖(가짜 정답지)을 못 읽는지 시험
    split         연습용·실전용 나누기(문서 묶음 단위, 씨앗). --write면 정본에 쓴다
    need          사람이 꼭 볼 문항 고르기(불일치·경고·실전용 거절·표본), 나머지 자동 승인. --more N으로 표본 추가
    review-html   사람이 꼭 볼 문항만 담은 검수 화면 HTML 파일 만들기
    merge         검수 화면이 내려받은 검수 기록을 정본에 합치기
    report        분포 보고(문항 수·모양·주제·꼬리표·문서당 상한·검수 현황)
    freeze        고정 기록(버전·SHA-256·문항 수) 쓰기
    judge         문항 하나에 답 하나를 규칙으로 판정해 보기
"""

import getpass
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import requests

from ..ledger import Ledger
from ..upload import BackendClient, UploadStop
from . import checks, cross, index_export, report, review, schema, split
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


def _work_dir(args) -> Path | None:
    """꾸러미를 만들 저장소 밖 임시 폴더. 저장소 안이면 None(상위 CLAUDE.md가 읽히고 정답지와 가까워진다)."""
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="documind-cross-"))
    work.mkdir(parents=True, exist_ok=True)
    marker = cross.repo_marker(work)
    if marker:
        print(f"꾸러미 폴더가 저장소 안에 있음({marker}). 저장소 밖 폴더를 --work로 주세요.", file=sys.stderr)
        return None
    return work


def cmd_cross(args) -> int:
    items = schema.load(args.file)
    today = _today(args)
    if args.from_record:
        result = cross.apply_record(items, Path(args.from_record), today)
    else:
        work = _work_dir(args)
        if work is None:
            return 2
        record_dir = Path(args.record_dir) if args.record_dir else (
            Path(args.file).parent / "cross" / datetime.now().strftime("%Y%m%d-%H%M%S"))
        ledger = _ledger(args)
        try:
            if args.dry_run:
                packets, no_doc, skipped = cross.plan(items, args.max_per_packet)
                cross.build_packets(packets, ledger, Path(args.root), work, args.scale)
                print(f"꾸러미 {len(packets)} · 물을 문항 {sum(len(packet.questions) for packet in packets)} · "
                      f"문서 없는 거절 {len(no_doc)} · 기계 검사 안 됨 {len(skipped)}")
                print(f"실행하지 않았다. 확인하는 세션이 볼 폴더: {work}")
                return 0
            result = cross.run(items, ledger, Path(args.root), record_dir, work, args.model, today,
                               runner=cross.run_claude, jobs=args.jobs, max_per_packet=args.max_per_packet,
                               scale=args.scale)
        except cross.CrossError as error:
            print(str(error), file=sys.stderr)
            return 1
        finally:
            ledger.close()
            if not args.dry_run and not args.keep_work:
                shutil.rmtree(work, ignore_errors=True)
        print(f"기록 폴더: {record_dir}")
    verdicts = result["verdicts"]
    print(f"꾸러미 {result['packets']} · 물은 문항 {result['asked']} · 문서 없는 거절 {result['no_doc']} · "
          + " · ".join(f"{name} {verdicts.get(name, 0)}" for name in schema.CROSS_VERDICTS))
    if result["skipped"]:
        print(f"기계 검사를 통과하지 않아 건너뜀 {len(result['skipped'])}: {', '.join(result['skipped'][:10])}")
    for key, problem in result["failed"]:
        print(f"꾸러미 실패 {key}: {problem}")
    if result["unanswered"]:
        print(f"답이 없는 문항 {len(result['unanswered'])}(다시 실행하면 이것만 푼다): {', '.join(result['unanswered'][:10])}")
    if args.write:
        schema.save(args.file, items)
    elif not args.from_record:
        print("정본에 쓰지 않았다. 쓰려면: evalset cross --from-record <기록 폴더> --write")
    return 0 if not result["failed"] and not result["unanswered"] else 1


def cmd_fence(args) -> int:
    work = _work_dir(args)
    if work is None:
        return 2
    try:
        result = cross.fence(work, args.model, runner=cross.run_claude)
    finally:
        if not args.keep_work:
            shutil.rmtree(work, ignore_errors=True)
    print(f"꾸러미 안 글 읽음: {'예' if result['read_inside'] else '아니오'} · "
          f"꾸러미 밖 정답지 새어 나옴: {'예' if result['leaked'] else '아니오'} · 거절된 도구 사용 {result['denials']}")
    print("통과" if result["passed"] else "실패 — 교차 확인을 돌리지 말 것")
    if not result["passed"]:
        print(result["stdout"][-2000:] or result["stderr"][-2000:])
    return 0 if result["passed"] else 1


def cmd_review_html(args) -> int:
    items = schema.load(args.file)
    ledger = _ledger(args)
    built_at = datetime.now()
    try:
        texts = checks.TextSource(ledger, args.root, args.index_dir)
        html, count = review.build_html(items, texts, ledger, built_at, Path(args.file).name)
    finally:
        ledger.close()
    if not count:
        print("사람이 볼 문항이 없다. need를 먼저 돌리세요.", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else (
        Path(args.file).parent / "review" / f"검수화면-{built_at.strftime('%Y%m%d-%H%M%S')}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"사람이 볼 문항 {count}개 → {out}")
    if not args.index_dir:
        print("색인 글(--index-dir) 없이 만들었다. 원본에서 뽑은 글이라 표가 한 줄로 보일 수 있다.")
    return 0


def cmd_merge(args) -> int:
    items = schema.load(args.file)
    try:
        records = review.load_records(args.records)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    result = review.merge(items, records)
    counts = result["counts"]
    print(" · ".join(f"{name} {counts[name]}" for name in (*review.RECORD_STATUSES, "이미 합침") if counts[name]) or "합칠 기록 없음")
    for error in result["errors"]:
        print(f"합치지 못함 {error}", file=sys.stderr)
    if result["errors"]:
        print("오류가 있어 정본에 쓰지 않았다. 기록 파일을 고친 뒤 다시 합치세요.", file=sys.stderr)
        return 1
    if counts["고침"]:
        print(f"고친 문항 {counts['고침']}개는 기계 검사를 다시 해야 한다: evalset check --write")
    if args.write:
        schema.save(args.file, items)
    return 0


def cmd_export_index(args) -> int:
    if not args.base_url.startswith(("http://", "https://")):
        print("--base-url은 http:// 또는 https://로 시작해야 합니다.", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else args.default_dir / "index_text" / args.index_backup
    ledger = _ledger(args)
    try:
        password = os.environ.get("DOCUMIND_ADMIN_PASSWORD") or getpass.getpass(f"{args.username} 비밀번호: ")
        client = BackendClient(args.base_url, requests.Session())
        client.login(args.username, password)
        result = index_export.export(client, ledger, out, args.base_url, args.index_backup, datetime.now(), args.limit)
    except UploadStop as stop:
        print(str(stop), file=sys.stderr)
        return 1
    finally:
        ledger.close()
    print(f"색인 문서 {result['targets']} · 받음 {result['written']} · 실패 {len(result['failed'])} → {out}")
    for doc_id, problem in result["failed"][:20]:
        print(f"  실패 {doc_id}: {problem}")
    return 0 if not result["failed"] else 1


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
    held = sum(1 for item in main if item["part"] == "실전")
    print(f"본 문항 {len(main)} · 연습 {len(main) - held} · 실전 {held} (씨앗 {args.seed})")
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

    export = sub.add_parser("export-index", help="서비스 색인 글 내보내기(데스크탑 챗봇이 떠 있어야 함)")
    export.add_argument("--base-url", required=True, help="챗봇 화면 주소(예: http://데스크탑이름). /api로 백엔드를 부른다")
    export.add_argument("--index-backup", required=True, help="지금 색인의 백업 이름(예: 20261004-201713). 폴더 이름과 기록에 쓴다")
    export.add_argument("--username", default="admin", help="관리자 아이디(기본 admin)")
    export.add_argument("--out", help=f"받을 폴더(기본: {default_file.parent / 'index_text' / '<백업 이름>'})")
    export.add_argument("--limit", type=int, help="받을 최대 문서 수(시험용)")
    export.set_defaults(func=cmd_export_index, default_dir=default_file.parent)

    check = with_file("check", "기계 검사")
    check.add_argument("--index-dir", help="내보낸 색인 글 폴더. 없으면 원본 파일에서 뽑은 글로 대조")
    check.add_argument("--write", action="store_true", help="검사 결과를 정본에 쓴다")
    check.set_defaults(func=cmd_check)

    check_cross = with_file("cross", "교차 확인(다른 Claude 세션이 정답지 없이 풂)")
    check_cross.add_argument("--model", default=cross.DEFAULT_MODEL, help=f"확인하는 세션의 모델(기본 {cross.DEFAULT_MODEL})")
    check_cross.add_argument("--jobs", type=int, default=2, help="동시에 돌릴 세션 수(기본 2)")
    check_cross.add_argument("--max-per-packet", type=int, default=cross.MAX_PER_PACKET, help="꾸러미 하나에 넣을 문항 수")
    check_cross.add_argument("--scale", type=float, default=cross.PDF_SCALE, help="PDF 쪽 그림 배율(기본 1.5)")
    check_cross.add_argument("--work", help="꾸러미를 만들 저장소 밖 폴더(기본: 새 임시 폴더)")
    check_cross.add_argument("--keep-work", action="store_true", help="실행 뒤 꾸러미 폴더를 지우지 않는다")
    check_cross.add_argument("--record-dir", help="질문·명령·출력 기록 폴더(기본: 정본 옆 cross/<시각>)")
    check_cross.add_argument("--from-record", help="이미 실행한 기록 폴더의 출력으로 채운다(다시 실행하지 않음)")
    check_cross.add_argument("--dry-run", action="store_true", help="꾸러미만 만들고 실행하지 않는다(폴더를 남김)")
    check_cross.add_argument("--write", action="store_true", help="교차 확인 결과를 정본에 쓴다")
    check_cross.set_defaults(func=cmd_cross)

    fenced = sub.add_parser("fence", help="교차 확인 세션이 꾸러미 밖을 못 읽는지 가짜 정답지로 시험")
    fenced.add_argument("--model", default=cross.DEFAULT_MODEL)
    fenced.add_argument("--work", help="시험 폴더(기본: 새 임시 폴더)")
    fenced.add_argument("--keep-work", action="store_true")
    fenced.set_defaults(func=cmd_fence)

    parts = with_file("split", "연습용·실전용 나누기")
    parts.add_argument("--seed", type=int, required=True)
    parts.add_argument("--held", type=float, default=split.HELD_RATIO, help="실전용 비율(기본 0.4)")
    parts.add_argument("--write", action="store_true")
    parts.set_defaults(func=cmd_split)

    need = with_file("need", "사람이 꼭 볼 문항 고르기")
    need.add_argument("--seed", type=int, required=True)
    need.add_argument("--sample", type=int, default=split.SAMPLE_SIZE, help="표본 수(기본 30)")
    need.add_argument("--more", type=int, help="표본을 이만큼 더 뽑는다(표본 오류가 2개 이상일 때)")
    need.add_argument("--write", action="store_true")
    need.set_defaults(func=cmd_need)

    screen = with_file("review-html", "검수 화면 HTML 만들기(사람이 꼭 볼 문항만)")
    screen.add_argument("--index-dir", help="내보낸 색인 글 폴더. 없으면 원본 파일에서 뽑은 글을 보여 준다")
    screen.add_argument("--out", help="HTML 파일(기본: 정본 옆 review/검수화면-<시각>.html)")
    screen.set_defaults(func=cmd_review_html)

    merged = with_file("merge", "검수 기록 합치기")
    merged.add_argument("--records", nargs="+", required=True, help="검수 화면이 내려받은 기록 파일(여러 개 가능)")
    merged.add_argument("--write", action="store_true", help="합친 결과를 정본에 쓴다")
    merged.set_defaults(func=cmd_merge)

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
