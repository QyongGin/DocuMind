"""명령줄: `python -m corpus trainset <명령>` — 학습 예시 만들기(설계 `docs/rag/m2/6단계-학습예시-설계-20261021.md`).

    plan       묶음 고르기: 종류별 개수(1회차 비율을 --size로 줄이거나 늘림)만큼 데이터셋용 색인의 청크를 고른다
    questions  질문 초안(초안 모델, ADR-0040)
    attach     근거 붙이기: 데이터셋 AI 서버 /query(평가용 옵션)의 운영 프롬프트·근거 8개·학습 전 A.X 답
    targets    목표 답 초안(ADR-0039). --shapes ga,na면 인용형도
    check      자동 검사(ADR-0037)와 중복 표시
    judge      Claude 판정(통과·탈락과 이유만, 저장소 밖 격리 폴더에서 `claude -p`)
    review-html  사람 표본 화면(Claude 판정은 사람이 고른 뒤에 보임)
    merge-review 화면이 내려받은 판정 기록을 합치고 Claude와 어긋난 수를 센다
    status     단계별·종류별 개수
    export     학습 파일(A.X 채팅 형식 JSONL)

데이터셋 AI 서버와 Ollama는 데스크탑 안쪽 주소에만 열려 있어 맥북에서는 SSH 터널로 부른다
(`docs/development/local-gpu/데이터셋-색인-절차.md`).
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import requests

from . import judge, pipeline, review
from .plan import ROUND1, dataset_documents, plan, scale

DEFAULT_MODEL = "gemma4:12b-it-qat"


def _batch_dir(args) -> Path:
    return Path(args.root).parent / "train" / args.batch


def cmd_plan(args) -> int:
    batch_dir = _batch_dir(args)
    if pipeline.path(batch_dir, "plan").exists():
        print(f"이미 계획이 있다: {pipeline.path(batch_dir, 'plan')} — 새 묶음 이름을 쓴다")
        return 1
    con = sqlite3.connect(Path(args.root) / "ledger.sqlite")
    documents = dataset_documents(con)
    skip = set()
    for other in (args.skip_batches or "").split(","):
        if other:
            skip |= {item["group_id"] for item in pipeline.read(Path(args.root).parent / "train" / other, "plan").values()
                     if item.get("group_id")}
    session = requests.Session()

    def fetch_chunks(document_id: int) -> list[dict]:
        response = session.get(f"{args.ai_url.rstrip('/')}/documents/{document_id}/chunks", timeout=120)
        response.raise_for_status()
        return response.json().get("chunks") or []

    quotas = scale(ROUND1, args.size)
    items = plan(documents, quotas, fetch_chunks, args.batch, args.seed, skip)
    pipeline.write(batch_dir, "plan", items, mode="w")
    made = {}
    for item in items:
        made[item["kind"]] = made.get(item["kind"], 0) + 1
    print(f"계획 {len(items)}개 (목표 {quotas}) → {pipeline.path(batch_dir, 'plan')}")
    print(f"종류별: {made}")
    return 0


def cmd_questions(args) -> int:
    counts = pipeline.run_questions(_batch_dir(args), requests.Session(), args.ollama_url, args.model, args.limit)
    print(dict(counts))
    return 0 if not counts.get("error") else 1


def cmd_attach(args) -> int:
    counts = pipeline.run_attach(_batch_dir(args), requests.Session(), args.ai_url, args.limit)
    print(dict(counts))
    return 0 if not counts.get("error") else 1


def cmd_targets(args) -> int:
    shapes = tuple(shape for shape in args.shapes.split(",") if shape)
    counts = pipeline.run_targets(_batch_dir(args), requests.Session(), args.ollama_url, args.model, shapes, args.limit)
    print(dict(counts))
    return 0 if not counts.get("error") else 1


def cmd_check(args) -> int:
    shapes = tuple(shape for shape in args.shapes.split(",") if shape)
    counts = pipeline.run_checks(_batch_dir(args), shapes)
    print(json.dumps(dict(counts), ensure_ascii=False, indent=1))
    return 0


def cmd_status(args) -> int:
    print(json.dumps(pipeline.status(_batch_dir(args)), ensure_ascii=False, indent=1))
    return 0


def cmd_judge(args) -> int:
    batch_dir = _batch_dir(args)
    todo = [record for record in pipeline.merged(batch_dir)
            if (record.get("keep") or {}).get("ga") and record.get("verdict") is None]
    todo = todo[: args.limit] if args.limit else todo
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="trainset-judge-"))
    print(f"판정할 예시 {len(todo)}개 · 작업 폴더 {work}")
    results, failed = judge.run(todo, work, args.model, jobs=args.jobs)
    pipeline.write(batch_dir, "judged", results)
    for name, why in failed:
        print(f"실패 {name}: {why}")
    passed = sum(result["verdict"] == "통과" for result in results)
    print(f"판정 {len(results)} · 통과 {passed} · 탈락 {len(results) - passed} · 실패한 작업 단위 {len(failed)}")
    return 0 if not failed else 1


def cmd_review_html(args) -> int:
    batch_dir = _batch_dir(args)
    chosen = review.sample(pipeline.merged(batch_dir), args.size, args.seed)
    out = Path(args.out) if args.out else batch_dir / "review.html"
    out.write_text(review.page(chosen, args.batch), encoding="utf-8")
    print(f"표본 {len(chosen)}개 → {out}")
    return 0


def cmd_merge_review(args) -> int:
    batch_dir = _batch_dir(args)
    human = review.read_record(Path(args.file))
    pipeline.write(batch_dir, "human", [{"id": item_id, **entry} for item_id, entry in human.items()])
    print(json.dumps(review.agreement(pipeline.merged(batch_dir), human), ensure_ascii=False, indent=1))
    return 0


def cmd_export(args) -> int:
    verdicts = json.loads(Path(args.verdicts).read_text(encoding="utf-8")) if args.verdicts else None
    if args.use_judge:
        verdicts = pipeline.verdicts(_batch_dir(args))
    kept = pipeline.export(_batch_dir(args), Path(args.out), args.shape, verdicts)
    print(f"학습 예시 {kept}개 → {args.out}")
    return 0


def add_parser(commands) -> None:
    trainset = commands.add_parser("trainset", help="학습 예시 만들기(M2 6단계)")
    sub = trainset.add_subparsers(dest="trainset_command", required=True)

    def with_batch(name: str, help_text: str):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("--batch", required=True, help="묶음 이름(예: r1-first). Assets/train/<묶음>/에 쌓는다")
        return parser

    planning = with_batch("plan", "묶음 고르기")
    planning.add_argument("--size", type=int, default=40, help="만들 예시 수(1회차 비율 그대로, 기본 40)")
    planning.add_argument("--seed", type=int, default=20261021)
    planning.add_argument("--ai-url", default="http://localhost:18100", help="데이터셋 AI 서버 주소(SSH 터널)")
    planning.add_argument("--skip-batches", help="쉼표로 묶음 이름: 그 묶음에서 쓴 문서 묶음은 고르지 않는다")
    planning.set_defaults(func=cmd_plan)

    questions = with_batch("questions", "질문 초안")
    questions.add_argument("--ollama-url", default="http://localhost:11535", help="데이터셋 스택 Ollama 주소(SSH 터널)")
    questions.add_argument("--model", default=DEFAULT_MODEL)
    questions.add_argument("--limit", type=int)
    questions.set_defaults(func=cmd_questions)

    attaching = with_batch("attach", "근거 붙이기")
    attaching.add_argument("--ai-url", default="http://localhost:18100")
    attaching.add_argument("--limit", type=int)
    attaching.set_defaults(func=cmd_attach)

    targets = with_batch("targets", "목표 답 초안")
    targets.add_argument("--ollama-url", default="http://localhost:11535")
    targets.add_argument("--model", default=DEFAULT_MODEL)
    targets.add_argument("--shapes", default="ga", help="쉼표로 모양: ga(결론 → 안내 → 번호), na(인용 → 결론)")
    targets.add_argument("--limit", type=int)
    targets.set_defaults(func=cmd_targets)

    checking = with_batch("check", "자동 검사")
    checking.add_argument("--shapes", default="ga")
    checking.set_defaults(func=cmd_check)

    judging = with_batch("judge", "Claude 판정")
    judging.add_argument("--model", default=judge.DEFAULT_MODEL)
    judging.add_argument("--jobs", type=int, default=2)
    judging.add_argument("--limit", type=int, help="판정할 예시 수(첫 묶음 40)")
    judging.add_argument("--work", help="작업 폴더(저장소 밖). 없으면 임시 폴더")
    judging.set_defaults(func=cmd_judge)

    reviewing = with_batch("review-html", "사람 표본 화면")
    reviewing.add_argument("--size", type=int, default=30)
    reviewing.add_argument("--seed", type=int, default=20261021)
    reviewing.add_argument("--out", help="화면 파일(기본: 묶음 폴더의 review.html)")
    reviewing.set_defaults(func=cmd_review_html)

    merging = with_batch("merge-review", "판정 기록 합치기")
    merging.add_argument("file", help="화면이 내려받은 판정기록-<묶음>.jsonl")
    merging.set_defaults(func=cmd_merge_review)

    with_batch("status", "단계별·종류별 개수").set_defaults(func=cmd_status)

    exporting = with_batch("export", "학습 파일 내보내기")
    exporting.add_argument("--out", required=True)
    exporting.add_argument("--shape", default="ga")
    exporting.add_argument("--verdicts", help="판정 JSON({예시 번호: '통과'|'탈락'}). 주면 통과만")
    exporting.add_argument("--use-judge", action="store_true", help="묶음의 판정(사람 > Claude)으로 통과만")
    exporting.set_defaults(func=cmd_export)
