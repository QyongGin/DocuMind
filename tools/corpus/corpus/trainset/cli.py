"""명령줄: `python -m corpus trainset <명령>` — 학습 예시 만들기(설계 `docs/rag/m2/6단계-학습예시-설계-20261021.md`).

    plan       묶음 고르기: 종류별 개수(1회차 비율이나 --kinds 비율을 --size로 줄이거나 늘림, --fill-from이면 모자란 종류만)만큼 데이터셋용 색인의 청크를 고른다
    questions  질문 초안(초안 모델, ADR-0040)
    attach     근거 붙이기: 데이터셋 AI 서버 /query(평가용 옵션)의 운영 프롬프트·근거 8개·학습 전 A.X 답
    probe      학습 전 A.X 답을 같은 프롬프트로 여러 번(표본 추출) 받아 아는 정도를 잰다(ADR-0042). --model이면 그 모델의 답(ADR-0053)
    targets    목표 답 초안(ADR-0039). --shapes ga,na면 인용형도. --rewrite-failed면 목표 답이 답 탓으로 떨어진 문항만 --model로 다시 쓴다(ADR-0057)
    check      자동 검사(ADR-0037)와 중복 표시
    judge      Claude 판정(통과·탈락과 이유만, 저장소 밖 격리 폴더에서 `claude -p`). --as-target·--rewritten-by면 목표 답 후보를 판정해 통과한 답을 올린다
    review-html  사람 표본 화면(Claude 판정은 사람이 고른 뒤에 보임)
    merge-review 화면이 내려받은 판정 기록을 합치고 Claude와 어긋난 수를 센다
    status     단계별·종류별 개수
    export     학습 파일(A.X 채팅 형식 JSONL)
    export-round 1회차 학습 파일: 여러 묶음에서 종류 비율대로, 학습 전 A.X가 틀리던 예시 먼저(모양은 결론 먼저 한 벌, ADR-0050)
    judge-probes 학습한 모델의 답 중 규칙으로 못 가른 답만 Claude 판정(4회차 선호 쌍, ADR-0053)
    pairs      선호 쌍 파일: 판정을 통과한 목표 답 대 학습한 모델의 틀린 답(과잉 거절·틀린 값·지어내기·거절 머리말)

데이터셋 AI 서버와 Ollama는 데스크탑 안쪽 주소에만 열려 있어 맥북에서는 SSH 터널로 부른다
(`docs/development/local-gpu/데이터셋-색인-절차.md`).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

import requests

from . import judge, model_targets, pairs, pipeline, review, timeline
from .plan import (REWORD, ROUND1, boilerplate_lines, dataset_documents, document_family, fill_quotas, parse_kinds,
                   plan, scale, trained_groups)

DEFAULT_MODEL = "gemma4:12b-it-qat"


def _batch_dir(args) -> Path:
    return Path(args.root).parent / "train" / args.batch


def _kinds(text: str) -> dict[str, int]:
    try:
        return parse_kinds(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _share(text: str) -> float:
    try:
        share = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"0~1 사이 수가 아니다: {text}") from error
    if not 0 <= share <= 1:
        raise argparse.ArgumentTypeError(f"0~1 사이 수가 아니다: {text}")
    return share


def load_chunks(documents: list[dict], ai_url: str, cache: Path) -> dict[int, list[dict]]:
    """데이터셋용 색인의 문서별 청크(AI 서버 /documents/{id}/chunks). 한 번 받으면 묶음 폴더 밖 캐시 파일에 두고 다시 쓴다.
    색인을 다시 만들면 캐시 파일을 지운다."""
    chunks: dict[int, list[dict]] = {}
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            chunks[int(entry["document_id"])] = entry["chunks"]
    session = requests.Session()
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("a", encoding="utf-8") as out:
        for document in documents:
            if document["document_id"] in chunks:
                continue
            response = session.get(f"{ai_url.rstrip('/')}/documents/{document['document_id']}/chunks", timeout=120)
            response.raise_for_status()
            chunks[document["document_id"]] = [{key: chunk.get(key) for key in ("id", "chunk_index", "content")}
                                               for chunk in response.json().get("chunks") or []]
            out.write(json.dumps({"document_id": document["document_id"], "chunks": chunks[document["document_id"]]},
                                 ensure_ascii=False) + "\n")
    return chunks


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
    if args.skip_trained:
        skip |= trained_groups(Path(args.root).parent / "train" / name for name in args.skip_trained.split(",") if name)
    if skip:
        print(f"뺀 문서 묶음 {len(skip)}")
    chunks = load_chunks(documents, args.ai_url, Path(args.root).parent / "train" / args.chunk_cache)
    boilerplate = boilerplate_lines(chunks)
    print(f"문서 {len(documents)} · 청크를 받은 문서 {len(chunks)} · 상투문 줄 {len(boilerplate)}")
    target = args.kinds or ROUND1
    quotas = scale(target, args.size)
    if args.fill_from:
        # 판정을 마친 묶음의 통과 수를 목표에서 빼고 모자란 종류만 배정한다(ADR-0041 결정 6)
        passed, planned, planned_passed = pipeline.yields([_batch_dir(args).parent / name
                                                           for name in args.fill_from.split(",") if name])
        quotas = fill_quotas(target, passed, planned, planned_passed, args.size)
        print(f"통과 {dict(passed)} · 계획 {dict(planned)} · 계획 종류별 통과 {dict(planned_passed)}")
        if not quotas:
            print("목표를 다 채웠다 — 새 묶음이 필요 없다")
            return 1
    items = plan(documents, quotas, lambda document_id: chunks.get(document_id, []), args.batch, args.seed, skip,
                 boilerplate, reword_share=args.reword_share)
    pipeline.write(batch_dir, "plan", items, mode="w")
    made = {}
    for item in items:
        made[item["kind"]] = made.get(item["kind"], 0) + 1
    print(f"계획 {len(items)}개 (목표 {quotas}) → {pipeline.path(batch_dir, 'plan')}")
    print(f"종류별: {made} · 말 바꾸기 {sum(item.get('wording') == REWORD for item in items)}개")
    return 0


def cmd_questions(args) -> int:
    counts = pipeline.run_questions(_batch_dir(args), requests.Session(), args.ollama_url, args.model, args.limit)
    print(dict(counts))
    return 0 if not counts.get("error") else 1


def cmd_attach(args) -> int:
    # 그날의 서비스 색인 모양으로 근거를 붙인다(ADR-0047). --no-timeline이면 데이터셋 색인 그대로(그 전 방식, 비교용)
    con = sqlite3.connect(Path(args.root) / "ledger.sqlite")
    dates = None if args.no_timeline else timeline.ledger_dates(con)
    # 답없음 예시의 확인처 블록을 가릴 문서 관계(재료 문서·같은 게시글·같은 묶음, ADR-0048 결정 2)
    counts = pipeline.run_attach(_batch_dir(args), requests.Session(), args.ai_url, args.limit, dates=dates,
                                 today=date.today().isoformat(), family=document_family(con),
                                 require_rerank=args.require_rerank)
    print(dict(counts))
    return 0 if not counts.get("error") else 1


def cmd_probe(args) -> int:
    counts = pipeline.run_probe(_batch_dir(args), requests.Session(), args.ollama_url, args.samples, args.temperature,
                                args.limit, model=args.model)
    print(dict(counts))
    return 0 if not counts.get("error") else 1


def cmd_targets(args) -> int:
    if args.rewrite_failed:
        # 목표 답이 답 탓으로 떨어진 문항만 이 모델로 다시 써서 따로 둔다(ADR-0057 결정 3). 판정은 judge --rewritten-by
        counts = model_targets.rewrite(_batch_dir(args), requests.Session(), args.ollama_url, args.model, args.limit)
        print(dict(counts))
        return 0 if not counts.get("error") else 1
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
    if args.as_target or args.rewritten_by:
        return _judge_candidates(batch_dir, args)
    records = pipeline.merged(batch_dir)
    todo = (pipeline.pick_for_judge(records, args.limit) if args.limit else
            [record for record in records if (record.get("keep") or {}).get("ga") and record.get("verdict") is None])
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="trainset-judge-"))
    print(f"판정할 예시 {len(todo)}개 · 작업 폴더 {work}")
    results, failed = judge.run(todo, work, args.model, jobs=args.jobs)
    pipeline.write(batch_dir, "judged", results)
    for name, why in failed:
        print(f"실패 {name}: {why}")
    passed = sum(result["verdict"] == "통과" for result in results)
    print(f"판정 {len(results)} · 통과 {passed} · 탈락 {len(results) - passed} · 실패한 작업 단위 {len(failed)}")
    return 0 if not failed else 1


def _judge_candidates(batch_dir: Path, args) -> int:
    # 목표 답이 답 탓으로 떨어진 문항의 목표 답 후보를 판정하고 통과한 답을 목표 답으로 올린다. 후보는 학습한 모델이 낸 답
    # (--as-target, ADR-0056)이거나 다른 초안 모델이 다시 쓴 목표 답(--rewritten-by, ADR-0057 결정 3)이다
    model, rewritten = args.as_target or args.rewritten_by, bool(args.rewritten_by)
    todo, failed = model_targets.pending(batch_dir, model, rewritten), []
    if todo:
        work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="trainset-judge-candidates-"))
        what = f"{model}이 다시 쓴 목표 답" if rewritten else f"목표 답 후보로 판정할 {model} 답"
        print(f"{what} {len(todo)}개 · 작업 폴더 {work}")
        results, failed = judge.run(todo, work, args.model, jobs=args.jobs)
        model_targets.record_verdicts(batch_dir, model, todo, results, rewritten)
        for name, why in failed:
            print(f"실패 {name}: {why}")
    counts = model_targets.promote(batch_dir, model, rewritten)
    print(" · ".join(f"{name} {counts[name]}" for name in ("대상", "올림", "통과한 후보 없음", "자동 검사를 통과한 후보 없음",
                                                           "판정 전")) + f" · 실패한 작업 단위 {len(failed)}")
    return 0 if not failed else 1


def cmd_judge_probes(args) -> int:
    batch_dir = _batch_dir(args)
    todo = pairs.pending(batch_dir, args.probe_model)
    if not todo:
        print("Claude 판정이 필요한 답이 없다(모두 규칙으로 갈렸거나 이미 판정함)")
        return 0
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="trainset-judge-probes-"))
    print(f"판정할 답 {len(todo)}개 · 작업 폴더 {work}")
    results, failed = judge.run_answers(todo, work, args.model, jobs=args.jobs)
    pipeline.write(batch_dir, pairs.verdict_step(args.probe_model), results)
    for name, why in failed:
        print(f"실패 {name}: {why}")
    print(f"판정 {len(results)} · {dict(sorted(Counter(result['verdict'] for result in results).items()))} · "
          f"실패한 작업 단위 {len(failed)}")
    return 0 if not failed else 1


def cmd_no_answer_copies(args) -> int:
    batch_dir = _batch_dir(args)
    if pipeline.path(batch_dir, "plan").exists():
        print(f"이미 계획이 있다: {pipeline.path(batch_dir, 'plan')} — 새 묶음 이름을 쓴다")
        return 1
    train = Path(args.root).parent / "train"
    plans, questions = pairs.no_answer_copies([train / name for name in args.from_batches.split(",") if name], args.batch)
    if not plans:
        print("사본을 만들 원본이 없다(판정 통과·자동 검사 통과한 답 있는 예시)")
        return 1
    pipeline.write(batch_dir, "plan", plans, mode="w")
    pipeline.write(batch_dir, "questions", questions, mode="w")
    print(f"답없음 사본 {len(plans)}개 → {pipeline.path(batch_dir, 'plan')} · 원본 묶음별 "
          f"{dict(Counter(plan['source_id'].rsplit('-', 1)[0] for plan in plans))}")
    return 0


def cmd_pairs(args) -> int:
    train = Path(args.root).parent / "train"
    lines, manifest = pairs.build([train / name for name in args.batches.split(",") if name], args.probe_model,
                                  [train / name for name in (args.copies or "").split(",") if name])
    print(json.dumps({key: value for key, value in manifest.items() if key != "ids"}, ensure_ascii=False, indent=1))
    if manifest["items"].get("unjudged"):
        print(f"Claude 판정 전인 답이 있는 문항 {manifest['items']['unjudged']}개 — judge-probes를 먼저 돌린다. 쌍 파일을 쓰지 않는다")
        return 1
    if manifest["legacy_prompts"] or manifest["old_refusal_left"]:
        print("지난 입력 규칙이나 거절 문장이 남았다 — 지금 운영 프롬프트로 근거를 다시 붙인 묶음만 쓴다. 쌍 파일을 쓰지 않는다")
        return 1
    pairs.write(lines, manifest, Path(args.out_dir))
    if manifest["dropped_over_refusal"]:
        print(f"지어내기 쌍이 모자라 과잉 거절 쌍 {manifest['dropped_over_refusal']}개를 뺐다 — 늘리려면 답 없는 질문 묶음을 더 만든다")
    print(f"선호 쌍 {manifest['size']}개 → {Path(args.out_dir) / 'pairs.jsonl'}")
    return 0


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


def cmd_export_round(args) -> int:
    train = Path(args.root).parent / "train"
    shapes = tuple(shape for shape in args.shapes.split(",") if shape)
    caps = {kind: int(count) for kind, count in (item.split("=") for item in args.cap.split(",") if item)} if args.cap else None
    manifest = pipeline.export_round([train / name for name in args.batches.split(",") if name], Path(args.out_dir),
                                     args.size, shapes, caps, args.max_citations)
    print(json.dumps({key: value for key, value in manifest.items() if key != "ids"}, ensure_ascii=False, indent=1))
    if args.size and manifest["size"] < args.size:
        print(f"통과한 예시가 모자라 {manifest['size']}개만 골랐다 — 묶음을 더 만든다")
    if manifest["old_refusal_left"]:
        print(f"지난 거절 문장이나 '(없는 것)' 자리표시가 {manifest['old_refusal_left']}줄에 남았다 — 입력 규칙의 글자가 다른 묶음이 섞였다. "
              "학습 파일로 쓰지 않는다")
        return 1
    return 0


def add_parser(commands) -> None:
    trainset = commands.add_parser("trainset", help="학습 예시 만들기(M2 6단계)")
    sub = trainset.add_subparsers(dest="trainset_command", required=True)

    def with_batch(name: str, help_text: str):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("--batch", required=True, help="묶음 이름(예: r1-first). Assets/train/<묶음>/에 쌓는다")
        return parser

    planning = with_batch("plan", "묶음 고르기")
    planning.add_argument("--size", type=int, default=40, help="만들 예시 수(--kinds 비율, 없으면 1회차 비율, 기본 40)")
    planning.add_argument("--kinds", type=_kinds,
                          help="쉼표로 종류=개수(예: fact=10,table=40,refuse_guide=22). 비율로 써서 --size로 줄이거나 늘린다. "
                               "--fill-from과 함께면 통과 목표 개수로 읽는다")
    planning.add_argument("--seed", type=int, default=20261021)
    planning.add_argument("--ai-url", default="http://localhost:18100", help="데이터셋 AI 서버 주소(SSH 터널)")
    planning.add_argument("--skip-batches", help="쉼표로 묶음 이름: 그 묶음에서 쓴 문서 묶음은 고르지 않는다")
    planning.add_argument("--skip-trained",
                          help="쉼표로 학습 파일(Assets/train/ 아래 경로, 예: round3/round-ga.jsonl,round4/pairs.jsonl): "
                               "그 파일의 예시가 쓴 문서 묶음은 고르지 않는다(학습한 모델이 본 문서, 5회차 ADR-0055)")
    planning.add_argument("--chunk-cache", default="chunks-dataset.jsonl",
                          help="문서별 청크 캐시 파일 이름(Assets/train/ 아래). 데이터셋 색인을 다시 만들면 지운다")
    planning.add_argument("--fill-from", help="쉼표로 판정을 마친 묶음 이름: 그 통과 수를 목표(--kinds, 없으면 1회차)에서 빼고 "
                                              "모자란 종류만 배정")
    planning.add_argument("--reword-share", type=_share, default=0.0,
                          help="글 있는 예시 중 질문의 핵심 낱말을 문서와 다른 말로 쓰게 할 몫(0~1, 기본 0)")
    planning.set_defaults(func=cmd_plan)

    questions = with_batch("questions", "질문 초안")
    questions.add_argument("--ollama-url", default="http://localhost:11535", help="데이터셋 스택 Ollama 주소(SSH 터널)")
    questions.add_argument("--model", default=DEFAULT_MODEL)
    questions.add_argument("--limit", type=int)
    questions.set_defaults(func=cmd_questions)

    attaching = with_batch("attach", "근거 붙이기")
    attaching.add_argument("--ai-url", default="http://localhost:18100")
    attaching.add_argument("--limit", type=int)
    attaching.add_argument("--no-timeline", action="store_true",
                           help="그날 없던 문서를 빼지 않고 데이터셋 색인 그대로 근거를 붙인다(ADR-0047 전 방식, 비교용)")
    attaching.add_argument("--require-rerank", action="store_true",
                           help="재순위가 실제로 쓰인 근거만 받는다(5회차, ADR-0055). 재순위 서버가 답하지 않아 순위 융합 "
                                "순서로 나온 근거는 실패로 남겨 다음 실행에서 다시 붙인다")
    attaching.set_defaults(func=cmd_attach)

    probing = with_batch("probe", "A.X 답 여러 번 받기(학습 전 모델의 아는 정도 ADR-0042, 학습한 모델의 답 ADR-0053)")
    probing.add_argument("--ollama-url", default="http://localhost:11535")
    probing.add_argument("--model", help="답을 받을 모델(예: ax40light-r3:q4km). 주면 probes-<모델>.jsonl에 따로 쌓는다. "
                                         "없으면 운영값 모델(학습 전 A.X)로 probes.jsonl에")
    probing.add_argument("--samples", type=int, default=pipeline.PROBE_SAMPLES)
    probing.add_argument("--temperature", type=float, default=pipeline.PROBE_TEMPERATURE)
    probing.add_argument("--limit", type=int)
    probing.set_defaults(func=cmd_probe)

    targets = with_batch("targets", "목표 답 초안")
    targets.add_argument("--ollama-url", default="http://localhost:11535")
    targets.add_argument("--model", default=DEFAULT_MODEL)
    targets.add_argument("--shapes", default="ga", help="쉼표로 모양: ga(결론 → 안내 → 번호), na(인용 → 결론)")
    targets.add_argument("--limit", type=int)
    targets.add_argument("--rewrite-failed", action="store_true",
                         help="목표 답이 답 탓으로 떨어진 문항만 --model로 다시 써서 targets-<모델>.jsonl에 둔다(ADR-0057). 문항의 "
                              "목표 답은 그대로 두고, judge --rewritten-by가 판정해 통과한 답만 올린다")
    targets.set_defaults(func=cmd_targets)

    checking = with_batch("check", "자동 검사")
    checking.add_argument("--shapes", default="ga")
    checking.set_defaults(func=cmd_check)

    judging = with_batch("judge", "Claude 판정")
    judging.add_argument("--model", default=judge.DEFAULT_MODEL)
    judging.add_argument("--jobs", type=int, default=2)
    judging.add_argument("--limit", type=int, help="판정할 예시 수(첫 묶음 40). 주면 종류별 개수(1회차 비율)를 지켜 고른다")
    judging.add_argument("--work", help="작업 폴더(저장소 밖). 없으면 임시 폴더")
    candidate_source = judging.add_mutually_exclusive_group()
    candidate_source.add_argument("--as-target", metavar="PROBE_MODEL",
                                  help="목표 답이 답 탓으로 떨어진 문항에서 probe --model로 받은 이 모델의 답을 목표 답 후보로 "
                                       "판정하고, 통과한 답을 목표 답으로 올린다(ADR-0056)")
    candidate_source.add_argument("--rewritten-by", metavar="DRAFT_MODEL",
                                  help="targets --rewrite-failed --model로 이 모델이 다시 쓴 목표 답을 판정하고, 통과한 답을 "
                                       "목표 답으로 올린다(ADR-0057)")
    judging.set_defaults(func=cmd_judge)

    probe_judging = with_batch("judge-probes", "학습한 모델 답 중 규칙으로 못 가른 답만 Claude 판정(선호 쌍, ADR-0053)")
    probe_judging.add_argument("--probe-model", required=True, help="probe --model로 답을 받은 모델(예: ax40light-r3:q4km)")
    probe_judging.add_argument("--model", default=judge.DEFAULT_MODEL, help="판정할 Claude 모델")
    probe_judging.add_argument("--jobs", type=int, default=2)
    probe_judging.add_argument("--work", help="작업 폴더(저장소 밖). 없으면 임시 폴더")
    probe_judging.set_defaults(func=cmd_judge_probes)

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

    round_export = sub.add_parser("export-round", help="1회차 학습 파일(여러 묶음에서 종류 비율대로, A.X가 틀리던 예시 먼저)")
    round_export.add_argument("--batches", required=True, help="쉼표로 묶음 이름(앞 묶음이 질문 중복에서 남는다)")
    round_export.add_argument("--size", type=int, default=200, help="고를 예시 수(1회차 비율대로). 0이면 통과한 예시를 모두 쓴다")
    round_export.add_argument("--cap", help="쉼표로 종류별 상한(예: refuse_guide=40,refuse_offtopic=15). --size 0일 때 쓴다")
    round_export.add_argument("--max-citations", type=int, help="목표 답의 출처 번호가 이보다 많은 예시를 뺀다")
    round_export.add_argument("--shapes", default="ga", help="쉼표로 모양(기본 ga 한 벌, ADR-0050 결정 7). 여럿이면 같은 예시")
    round_export.add_argument("--out-dir", required=True)
    round_export.set_defaults(func=cmd_export_round)

    pairing = sub.add_parser("pairs", help="선호 쌍 파일(판정 통과 목표 답 대 학습한 모델의 틀린 답, ADR-0053)")
    pairing.add_argument("--batches", required=True, help="쉼표로 묶음 이름(앞 묶음이 질문 중복에서 남는다)")
    pairing.add_argument("--probe-model", required=True, help="probe --model로 답을 받은 모델(예: ax40light-r3:q4km)")
    pairing.add_argument("--out-dir", required=True, help="pairs.jsonl과 manifest.json을 둘 폴더")
    pairing.add_argument("--copies", help="쉼표로 답없음 사본 묶음 이름: 사본마다 사본 쌍과 원본 쌍을 더한다")
    pairing.set_defaults(func=cmd_pairs)

    copying = with_batch("no-answer-copies", "답 있는 판정 통과 예시에서 답 근거를 뺀 답없음 사본 계획(4회차 쌍, ADR-0053 변경 메모)")
    copying.add_argument("--from-batches", required=True, help="쉼표로 원본 묶음 이름(판정·3회차 답 판정까지 마친 묶음)")
    copying.set_defaults(func=cmd_no_answer_copies)
