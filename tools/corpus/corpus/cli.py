"""명령줄: `python -m corpus <명령>`.

    collect        학교 누리집에서 수집(이어 받기)
    export-review  사람이 확인할 칸을 CSV로 내보내기
    import-review  확인한 CSV를 대장에 반영하고, 개인정보 '제외' 원본을 지운다
    add-file       이미 가진 파일을 대장에 등록(예: 2026학년도 모집요강)
    remeasure      글을 읽지 못한 행을 원본으로 다시 재기(형식 오인 정정, 빈 파일 정리). 요청은 보내지 않는다
    stats          대장 집계(형식·주제·개인정보·첨부 실측 크기)
    failures       실패 목록
    upload         대장 행을 서비스 백엔드 API로 올리기(관리자 비밀번호는 실행 때 입력, 이어 올리기)
"""

import argparse
import getpass
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from . import extract, pii, upload
from .collect import TARGETS, Collector, counts_dict, remeasure
from .ledger import Ledger
from .polite import KST, PoliteSession, Stop

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "Assets" / "corpus"


def ledger_at(root: Path) -> Ledger:
    return Ledger(root / "ledger.sqlite")


def cmd_collect(args) -> int:
    root = Path(args.root)
    targets = args.only.split(",") if args.only else list(TARGETS)
    unknown = [target for target in targets if target not in TARGETS]
    if unknown:
        print(f"모르는 대상: {unknown}. 가능한 값: {', '.join(TARGETS)}", file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    log_file = open(root / "collect.log", "a", encoding="utf-8")

    def log(message: str) -> None:
        line = f"{datetime.now(KST).strftime('%H:%M:%S')} {message}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    ledger = ledger_at(root)
    session = PoliteSession(min_interval=args.interval, max_requests=args.max_requests)
    collector = Collector(session, ledger, root, datetime.now(KST).date(), log=log)
    log(f"시작: 대상 {targets}, 공지 기준일 {collector.cutoff.isoformat()}, 간격 {args.interval}초")
    code = 0
    try:
        collector.run(targets)
    except Stop as reason:
        log(f"멈춤: {reason}")
        code = 3
    except KeyboardInterrupt:
        log("멈춤: 사용자가 중단")
        code = 130
    finally:
        log(f"요청 {session.requests_made}회, 결과 {json.dumps(counts_dict(collector.counts), ensure_ascii=False)}")
        ledger.close()
        log_file.close()
    return code


def cmd_export(args) -> int:
    ledger = ledger_at(Path(args.root))
    count = ledger.export_review(args.csv, only_unreviewed=args.unreviewed)
    ledger.close()
    print(f"{count}행을 {args.csv}에 썼다")
    return 0


def cmd_import(args) -> int:
    root = Path(args.root)
    ledger = ledger_at(root)
    count = ledger.import_review(args.csv)
    removed = ledger.purge_excluded(root)
    ledger.close()
    print(f"{count}행 반영, 개인정보 '제외' 원본 {len(removed)}개 삭제")
    return 0


def cmd_add_file(args) -> int:
    root = Path(args.root)
    source = Path(args.path)
    ledger = ledger_at(root)
    fmt = extract.sniff_format(source.name, source.read_bytes()[:8])
    relpath = Path("raw") / f"{args.doc_id}.{extract.file_ext(source.name)}"
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    data = target.read_bytes()
    row = {
        "doc_id": args.doc_id, "site": args.site, "kind": "file", "url": args.url or f"local:{source.name}",
        "title": args.title or source.name, "collected_at": datetime.now(KST).date().isoformat(),
        "file_path": relpath.as_posix(), "format": fmt, "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data), "topic": args.topic, "academic_year": args.year, "valid_until": args.valid_until,
        "group_id": args.group, "notes": args.notes,
    }
    text = None
    if fmt == "pdf":
        chars, pages, text = extract.pdf_metrics(str(target))
        row.update(text_chars=chars, image_heavy=int(extract.image_heavy_pdf(chars, pages)))
    elif fmt == "hwp":
        chars, tables, text, _ = extract.hwp_metrics(str(target))
        row.update(text_chars=chars, table_count=tables, image_heavy=0)
    status, reason = pii.judge(row["title"], text) if text is not None else ("보류", f"2차 검사 못 함(형식 {fmt})")
    row.update(pii_status=status, pii_reason=reason,
               index_status=extract.index_status(status, args.valid_until, datetime.now(KST).date()))
    ledger.upsert(row)
    ledger.close()
    print(f"등록: {args.doc_id} ({fmt}, {len(data)} bytes, 개인정보 {status})")
    return 0


def cmd_remeasure(args) -> int:
    root = Path(args.root)
    ledger = ledger_at(root)
    report = remeasure(ledger, root, datetime.now(KST).date())
    ledger.close()
    print(json.dumps(report, ensure_ascii=False))
    return 0


def cmd_stats(args) -> int:
    ledger = ledger_at(Path(args.root))
    print(json.dumps(ledger.stats(), ensure_ascii=False, indent=2))
    ledger.close()
    return 0


def cmd_failures(args) -> int:
    ledger = ledger_at(Path(args.root))
    rows = ledger.con.execute(
        "SELECT at, stage, url, doc_id, error FROM failures ORDER BY id DESC LIMIT ?", (args.limit,)
    ).fetchall()
    for row in rows:
        print(" | ".join("" if value is None else str(value) for value in row))
    ledger.close()
    return 0


def cmd_upload(args) -> int:
    if not args.base_url.startswith(("http://", "https://")):
        print("--base-url은 http:// 또는 https://로 시작해야 합니다.", file=sys.stderr)
        return 2
    root = Path(args.root)
    ledger = ledger_at(root)
    try:
        formats = args.formats.split(",") if args.formats else None
        rows = upload.select_rows(ledger.con, args.set, formats)
        by_format = Counter(row["format"] for row in rows)
        print(f"대상 {args.set} · 주소 {args.base_url} · 고른 행 {len(rows)}개 "
              f"({', '.join(f'{fmt} {n}' for fmt, n in sorted(by_format.items()))})")
        if args.dry_run:
            for row in rows[:5]:
                print(f"  {row['doc_id']} → {upload.upload_filename(row['title'], row['format'])} · 카테고리 {row.get('topic') or '-'}")
            return 0
        if not args.yes and input("이 주소로 올릴까요? (y/N) ").strip().lower() != "y":
            print("올리지 않았습니다.")
            return 1
        password = os.environ.get("DOCUMIND_ADMIN_PASSWORD") or getpass.getpass(f"{args.username} 비밀번호: ")
        client = upload.BackendClient(args.base_url, requests.Session())
        client.login(args.username, password)
        counts = upload.Uploader(ledger.con, root, client, args.set).run(rows, args.retry_failed, args.limit)
        print(f"끝: 올림 {counts['ready']} · 이미 있음 {counts['exists']} · 실패 {counts['failed']} · "
              f"전에 끝나 건너뜀 {counts['skipped_done']}")
        return 0 if counts["failed"] == 0 else 1
    except upload.UploadStop as stop:
        print(str(stop), file=sys.stderr)
        return 1
    finally:
        ledger.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="corpus",
        description="인하공전 공개 문서 수집기와 문서 대장",
        epilog="본 제품은 한컴의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.",
    )
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="corpus 폴더 (기본: 저장소 Assets/corpus)")
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect", help="수집(이어 받기)")
    collect.add_argument("--only", help=f"쉼표로 대상 고르기: {','.join(TARGETS)}")
    collect.add_argument("--interval", type=float, default=2.0, help="요청 시작 간격(초, 2 이상)")
    collect.add_argument("--max-requests", type=int, help="요청 상한(시험 실행용)")
    collect.set_defaults(func=cmd_collect)

    export = commands.add_parser("export-review", help="확인 칸 CSV 내보내기")
    export.add_argument("csv")
    export.add_argument("--unreviewed", action="store_true", help="확인 전 행만")
    export.set_defaults(func=cmd_export)

    import_ = commands.add_parser("import-review", help="확인 CSV 반영 + 제외 원본 삭제")
    import_.add_argument("csv")
    import_.set_defaults(func=cmd_import)

    add = commands.add_parser("add-file", help="가진 파일을 대장에 등록")
    add.add_argument("path")
    add.add_argument("--doc-id", required=True)
    add.add_argument("--site", required=True)
    add.add_argument("--title")
    add.add_argument("--url")
    add.add_argument("--topic")
    add.add_argument("--year", type=int)
    add.add_argument("--valid-until")
    add.add_argument("--group")
    add.add_argument("--notes")
    add.set_defaults(func=cmd_add_file)

    again = commands.add_parser("remeasure", help="읽지 못한 행 다시 재기(요청 없음)")
    again.set_defaults(func=cmd_remeasure)

    stats = commands.add_parser("stats", help="대장 집계")
    stats.set_defaults(func=cmd_stats)

    failures = commands.add_parser("failures", help="실패 목록")
    failures.add_argument("--limit", type=int, default=50)
    failures.set_defaults(func=cmd_failures)

    up = commands.add_parser("upload", help="대장 행을 서비스 백엔드로 올리기(비밀번호는 실행 때 입력)")
    up.add_argument("--base-url", required=True, help="챗봇 화면 주소(예: http://데스크탑이름). /api로 백엔드를 부른다")
    up.add_argument("--set", choices=sorted(upload.SELECTIONS), required=True,
                    help="service: 서비스 색인(색인 행) / dataset: 데이터셋용 색인(학습 몫)")
    up.add_argument("--username", default="admin", help="관리자 아이디(기본 admin)")
    up.add_argument("--formats", help="쉼표로 형식 고르기(예: hwp,html). 표본 시험용")
    up.add_argument("--limit", type=int, help="이번에 올릴 최대 문서 수. 표본 시험용")
    up.add_argument("--retry-failed", action="store_true", help="실패로 적힌 행도 다시 올린다")
    up.add_argument("--dry-run", action="store_true", help="고른 행 수와 파일 이름만 보여 준다(요청 없음)")
    up.add_argument("--yes", action="store_true", help="확인 질문 없이 바로 올린다")
    up.set_defaults(func=cmd_upload)

    args = parser.parse_args(argv)
    if getattr(args, "interval", 2.0) < 2.0:
        parser.error("요청 간격은 2초 이상이어야 한다(수집 규칙)")
    return args.func(args)
