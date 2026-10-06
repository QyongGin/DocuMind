"""교차 확인(결정 ⑦-1~⑦-4): 정답지를 쓴 세션과 다른 Claude 세션이 정답지를 보지 않고 질문을 푼다.

- 원본은 서비스 변환(OpenDataLoader PDF·ai-server 로더)을 거치지 않은 것으로 준다(⑦-2). HTML은 수집기가 저장한
  본문 영역의 원본 HTML(꾸밈만 지우고 `rowspan`·`colspan`은 남김), PDF는 쪽 그림 + 같은 쪽의 PDFium 글자,
  HWP는 수집기의 글자 추출이다.
- 근거 문서 전체를 주고, 정답지가 인용한 위치는 알려 주지 않는다(⑦-3). 거절 문항은 가까운 문서 전체를 준다.
- Claude Code를 비대화형(`claude -p`)으로, 저장소 밖 임시 폴더의 꾸러미 안에서, 읽기 도구만 주고 실행한다(⑦-4).
  `--restricted`로 파일 도구를 꾸러미 폴더 안에 가두고 사용자·프로젝트 설정을 읽지 않으며, `--safe-mode`로
  CLAUDE.md·스킬·출력 형식 같은 사용자 맞춤을 끈다. 폴더 밖을 정말 못 읽는지는 `fence`(가짜 정답지 시험)로 확인한다.
  저장소 안에서 돌리면 상위 폴더의 CLAUDE.md가 읽히므로 저장소 밖 임시 폴더를 쓴다.
- 답은 결정 ②의 규칙 판정(`judge`)으로 정답지와 비교한다. 맞음이면 일치, 애매면 애매, 나머지는 불일치.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import pypdfium2
from bs4 import Comment

from .. import extract, hwp
from ..ledger import Ledger
from .judge import judge

DEFAULT_MODEL = "claude-opus-5-5"
TOOLS = "Read,Grep,Glob"
MAX_PER_PACKET = 8
PDF_SCALE = 1.5  # 72dpi × 1.5 = 108dpi. 표 글자를 읽을 수 있고 369쪽 PDF도 약 100MB 안쪽
TIMEOUT_SECONDS = 30 * 60
NOT_FOUND = "문서에서 확인할 수 없습니다"
READERS = {
    "html": "원본 HTML(본문, 꾸밈 제거)",
    "pdf": "pypdfium2 쪽 그림+글자",
    "hwp": "수집기 HWP 글자",
    "hwpx": "수집기 HWPX 글자",
}
NO_DOC_READER = "가까운 문서 없음 — 부재 확인 기록으로 대신"
DROP_TAGS = ("script", "style", "noscript", "input", "select", "option", "button", "textarea",
             "colgroup", "col", "iframe", "svg")
UNWRAP_TAGS = ("div", "span", "article", "section", "form", "fieldset", "font")
KEEP_ATTRS = ("rowspan", "colspan")

# 확인하는 세션에 주는 지시문. 정답지·인용 위치는 넣지 않는다. 바꾸면 이전 실행과 결과를 나란히 비교할 수 없다
PROMPT = f"""너는 학교 문서로 만든 시험지의 교차 확인을 맡았다. 이 폴더 밖의 파일은 읽지 않는다.

1. questions.json의 질문마다 docs 폴더의 문서만 근거로 답한다. 문서 밖 지식이나 짐작은 쓰지 않는다.
2. 문서는 전체가 들어 있다. 질문과 관련된 곳을 직접 찾아 끝까지 읽는다. 표 아래 단서(※)·예외·다른 학년도 값도 확인한다.
3. HTML 파일은 원본 HTML이다(rowspan·colspan으로 칸이 합쳐져 있다). PDF는 쪽마다 그림(page-NNN.png)과 글자(page-NNN.txt)가 있다. 표와 숫자는 그림으로 확인한다.
4. 답이 문서에 없으면 answer에 "{NOT_FOUND}"라고 쓴다.
5. 출력은 JSON 하나만 쓴다: {{"answers": [{{"id": "문항 ID", "answer": "한두 문장 답", "quote": "근거로 쓴 원문 글(그대로)", "where": "파일 이름과 쪽"}}]}}. 모든 질문에 답한다.
"""


class CrossError(Exception):
    """꾸러미를 만들거나 결과를 읽지 못함."""


@dataclass
class Source:
    doc_id: str
    reader: str
    files: list[str]  # docs 폴더 안 상대 경로


@dataclass
class Packet:
    key: str
    docs: tuple[str, ...]
    questions: list[dict] = field(default_factory=list)


def source_name(doc_id: str) -> str:
    return doc_id.replace("/", "__")


def clean_html(html: str) -> str:
    """꾸밈(속성·스크립트·스타일·입력 칸)만 지우고 글과 표 구조(`rowspan`·`colspan`)는 남긴다."""
    document = extract.soup(html)
    for node in document(DROP_TAGS):
        node.decompose()
    for comment in document.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for image in document("img"):
        alt = (image.get("alt") or "").strip()
        image.replace_with(f"[그림: {alt}]" if alt else "")
    for node in document(UNWRAP_TAGS):
        node.unwrap()
    for tag in document.find_all(True):
        tag.attrs = {key: value for key, value in tag.attrs.items() if key in KEEP_ATTRS}
    return re.sub(r"\n\s*\n+", "\n", str(document)).strip() + "\n"


def write_source(ledger: Ledger, corpus_root: Path, doc_id: str, dest: Path, scale: float = PDF_SCALE) -> Source:
    """문서 하나를 ⑦-2의 방법으로 읽어 `dest`에 쓴다."""
    row = ledger.get(doc_id)
    if not row or not row.get("file_path"):
        raise CrossError(f"원본 파일이 대장에 없음: {doc_id}")
    path = Path(corpus_root) / row["file_path"]
    if not path.exists():
        raise CrossError(f"원본 파일이 없음: {path}")
    fmt, name = row["format"], source_name(doc_id)
    if fmt not in READERS:
        raise CrossError(f"교차 확인이 아직 읽지 못하는 형식: {fmt} ({doc_id})")
    dest.mkdir(parents=True, exist_ok=True)
    if fmt == "html":
        target = dest / f"{name}.html"
        target.write_text(clean_html(path.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        return Source(doc_id, READERS[fmt], [target.name])
    if fmt == "pdf":
        folder = dest / name
        folder.mkdir(exist_ok=True)
        files = []
        document = pypdfium2.PdfDocument(str(path))
        try:
            for number, page in enumerate(document, 1):
                stem = f"page-{number:03d}"
                page.render(scale=scale).to_pil().save(folder / f"{stem}.png")
                textpage = page.get_textpage()
                (folder / f"{stem}.txt").write_text(textpage.get_text_range(), encoding="utf-8")
                textpage.close()
                page.close()
                files += [f"{name}/{stem}.png", f"{name}/{stem}.txt"]
        finally:
            document.close()
        return Source(doc_id, READERS[fmt], files)
    if fmt == "hwp":
        result = hwp.extract(str(path))
        if result.encrypted or result.distribution:
            raise CrossError(f"암호 또는 배포용 HWP라 글을 읽지 못함: {doc_id}")
        text = result.text
    else:
        text = extract.hwpx_metrics(str(path))[2]
    target = dest / f"{name}.txt"
    target.write_text(text, encoding="utf-8")
    return Source(doc_id, READERS[fmt], [target.name])


def packet_docs(item: dict) -> tuple[str, ...]:
    """확인하는 세션에 줄 문서: 답 있는 문항은 근거 문서들, 거절 문항은 가까운 문서."""
    if item["shape"] == "거절":
        near = (item.get("refusal") or {}).get("near")
        return (near,) if near else ()
    return tuple(sorted(dict.fromkeys(entry["doc"] for entry in item["evidence"])))


def plan(items: list[dict], max_per_packet: int = MAX_PER_PACKET) -> tuple[list[Packet], list[dict], list[str]]:
    """교차 확인할 문항을 같은 문서끼리 꾸러미로 묶는다.

    돌려주는 것: (꾸러미, 문서가 없는 거절 문항, 기계 검사를 통과하지 않아 건너뛴 문항 ID).
    이미 교차 확인 결과가 있는 문항은 건드리지 않아 다시 실행하면 남은 문항만 푼다.
    """
    groups: dict[tuple[str, ...], list[dict]] = {}
    no_doc, skipped = [], []
    for item in sorted(items, key=lambda entry: entry["id"]):
        if item.get("cross"):
            continue
        machine = item.get("machine")
        if not machine or machine.get("errors"):
            skipped.append(item["id"])
            continue
        docs = packet_docs(item)
        if not docs:
            no_doc.append(item)
            continue
        groups.setdefault(docs, []).append(item)
    packets = []
    for docs in sorted(groups):
        members = groups[docs]
        for start in range(0, len(members), max_per_packet):
            chunk = members[start:start + max_per_packet]
            packets.append(Packet(f"p{len(packets) + 1:03d}", docs,
                                  [{"id": item["id"], "question": item["question"]} for item in chunk]))
    return packets, no_doc, skipped


def claude_command(model: str, prompt: str = PROMPT) -> list[str]:
    """확인하는 세션 실행 명령. 읽기 도구만, 파일 도구는 작업 폴더 안에만, 사용자 맞춤·MCP·대화 저장 없음,
    허락을 물어야 하는 일은 모두 거절."""
    return ["claude", "-p", prompt, "--output-format", "json", "--model", model, "--tools", TOOLS,
            "--restricted", "--safe-mode", "--permission-prompts", "none", "--strict-mcp-config",
            "--no-session-persistence"]


def repo_marker(path: Path) -> Path | None:
    """`path`나 그 위 폴더에 저장소 표시(.git·CLAUDE.md·AGENTS.md)가 있으면 그 파일. 꾸러미는 이런 곳 밖에 둔다."""
    for folder in (Path(path).resolve(), *Path(path).resolve().parents):
        for name in (".git", "CLAUDE.md", "AGENTS.md"):
            if (folder / name).exists():
                return folder / name
    return None


def run_claude(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=TIMEOUT_SECONDS)


def claude_version(runner: Callable = run_claude) -> str:
    completed = runner(["claude", "--version"], Path.cwd())
    return (completed.stdout or "").split("(")[0].strip() or "판 모름"


def parse_output(stdout: str) -> list[dict]:
    """`claude -p --output-format json`의 출력에서 답 목록을 꺼낸다."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise CrossError(f"Claude Code 출력이 JSON이 아님: {stdout[:200]!r}") from error
    if envelope.get("is_error"):
        raise CrossError(f"Claude Code 오류: {envelope.get('result')}")
    text = str(envelope.get("result") or "")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise CrossError(f"답에 JSON이 없음: {text[:200]!r}")
    try:
        answers = json.loads(match.group(0)).get("answers")
    except (json.JSONDecodeError, AttributeError) as error:
        raise CrossError(f"답 JSON을 읽지 못함: {match.group(0)[:200]!r}") from error
    if not isinstance(answers, list) or not all(
            isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("answer"), str)
            for entry in answers):
        raise CrossError("answers는 id·answer가 있는 목록이어야 함")
    return answers


def verdict(label: str) -> str:
    return {"맞음": "일치", "애매": "애매"}.get(label, "불일치")


def apply_answers(items: list[dict], packet: Packet, answers: list[dict], model_label: str, reader: str,
                  today: date) -> list[str]:
    """꾸러미의 답을 판정해 `cross` 칸에 쓴다. 답이 없는 문항 ID를 돌려준다(다음 실행에서 다시 푼다)."""
    by_id = {item["id"]: item for item in items}
    wanted = {question["id"] for question in packet.questions if question["id"] in by_id}
    answered = {item_id for item_id in wanted if by_id[item_id].get("cross")}  # 이미 채운 문항은 그대로 둔다
    for entry in answers:
        if entry["id"] not in wanted or entry["id"] in answered:
            continue
        answered.add(entry["id"])
        item = by_id[entry["id"]]
        label = judge(item, entry["answer"])["label"]
        item["cross"] = {"model": model_label, "reader": reader, "answer": entry["answer"],
                         "quote": entry.get("quote"), "where": entry.get("where"),
                         "verdict": verdict(label), "label": label, "at": today.isoformat()}
    return sorted(wanted - answered)


def mark_no_doc(items: list[dict], today: date) -> None:
    """가까운 문서가 없는 거절 문항: 줄 원본이 없어 풀지 않고, 부재 확인 기록(결정 ③)으로 대신한다."""
    for item in items:
        item["cross"] = {"model": None, "reader": NO_DOC_READER, "answer": None, "quote": None, "where": None,
                         "verdict": "일치", "label": None, "at": today.isoformat()}


def build_packets(packets: list[Packet], ledger: Ledger, corpus_root: Path, work: Path,
                  scale: float = PDF_SCALE) -> dict[str, list[Source]]:
    """꾸러미 폴더를 만든다: `<work>/<key>/questions.json`, `<work>/<key>/docs/…`. 문서는 한 번만 읽어 복사한다."""
    cache_root = work / "_docs"
    cache: dict[str, Source] = {}
    sources: dict[str, list[Source]] = {}
    for packet in packets:
        folder = work / packet.key
        docs = folder / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        for doc_id in packet.docs:
            if doc_id not in cache:
                cache[doc_id] = write_source(ledger, corpus_root, doc_id, cache_root / source_name(doc_id), scale)
            origin = cache_root / source_name(doc_id)
            for child in origin.iterdir():
                target = docs / child.name
                if child.is_dir():
                    shutil.copytree(child, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, target)
        (folder / "questions.json").write_text(
            json.dumps({"questions": packet.questions}, ensure_ascii=False, indent=1), encoding="utf-8")
        sources[packet.key] = [cache[doc_id] for doc_id in packet.docs]
    return sources


def save_record(record_dir: Path, packet: Packet, sources: list[Source], command: list[str], model_label: str) -> Path:
    """기록용 사본: 질문·문서 목록·실행 명령(정답지 없음). 그림 같은 큰 파일은 남기지 않는다(다시 만들 수 있음)."""
    folder = record_dir / packet.key
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "packet.json").write_text(json.dumps({
        "model": model_label,
        "questions": packet.questions,
        "docs": [{"doc_id": source.doc_id, "reader": source.reader, "files": len(source.files)} for source in sources],
        "command": command,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return folder


def read_record(record_dir: Path) -> list[tuple[Packet, str, str, str]]:
    """기록 폴더의 꾸러미와 저장한 출력을 읽는다: (꾸러미, 모델, 읽은 방법, 출력)."""
    found = []
    for folder in sorted(path for path in Path(record_dir).iterdir() if path.is_dir()):
        packet_file, output_file = folder / "packet.json", folder / "output.json"
        if not packet_file.exists() or not output_file.exists():
            continue
        saved = json.loads(packet_file.read_text(encoding="utf-8"))
        packet = Packet(folder.name, tuple(doc["doc_id"] for doc in saved["docs"]), saved["questions"])
        reader = " + ".join(dict.fromkeys(doc["reader"] for doc in saved["docs"]))
        found.append((packet, saved["model"], reader, output_file.read_text(encoding="utf-8")))
    return found


FENCE_PROMPT = """폴더 경계 시험이다. 아래를 차례로 해 보고, 한 일과 읽은 내용을 그대로 적는다. 못 했으면 왜 못 했는지 적는다.
1. docs/notice.txt를 Read로 읽고 '확인 글자'를 적는다.
2. {outside} 파일을 Read로 읽고 내용을 그대로 적는다.
3. {parent} 폴더에서 Grep으로 'OUTSIDE-'를 찾아 걸린 줄을 그대로 적는다.
4. {parent} 폴더를 Glob('**/*')으로 나열한다.
"""


def fence(work: Path, model: str, runner: Callable = run_claude) -> dict:
    """가짜 정답지 시험: 꾸러미 밖에 둔 정답지를 확인하는 세션이 읽지 못하는지 본다.

    꾸러미 안 글자(`inside`)는 읽어야 하고(시험이 너무 막혀서 통과하는 것을 막음) 밖 글자(`outside`)는 출력에
    없어야 통과다. Claude Code 판이 바뀌면 다시 돌린다.
    """
    inside, outside = f"INSIDE-{uuid.uuid4().hex[:10]}", f"OUTSIDE-{uuid.uuid4().hex[:10]}"
    packet = work / "packet"
    (packet / "docs").mkdir(parents=True, exist_ok=True)
    (packet / "docs" / "notice.txt").write_text(f"가나대학 공지\n확인 글자: {inside}\n", encoding="utf-8")
    answer_key = work / "answer_key.json"
    answer_key.write_text(json.dumps({"ev-0001": {"answer": outside}}, ensure_ascii=False), encoding="utf-8")
    command = claude_command(model, FENCE_PROMPT.format(outside=answer_key, parent=work))
    completed = runner(command, packet)
    stdout = completed.stdout or ""
    try:
        denials = len(json.loads(stdout).get("permission_denials") or [])
    except (json.JSONDecodeError, AttributeError):
        denials = None
    read_inside, leaked = inside in stdout, outside in stdout
    return {"passed": read_inside and not leaked, "read_inside": read_inside, "leaked": leaked,
            "denials": denials, "returncode": completed.returncode, "stdout": stdout,
            "stderr": completed.stderr or "", "command": command}


def run(items: list[dict], ledger: Ledger, corpus_root: Path, record_dir: Path, work: Path, model: str,
        today: date, runner: Callable = run_claude, jobs: int = 2, max_per_packet: int = MAX_PER_PACKET,
        scale: float = PDF_SCALE) -> dict:
    """꾸러미를 만들고 확인하는 세션을 실행해 `cross` 칸을 채운다. `work`는 저장소 밖 임시 폴더여야 한다."""
    packets, no_doc, skipped = plan(items, max_per_packet)
    mark_no_doc(no_doc, today)
    model_label = f"{model} · 다른 세션 · Claude Code {claude_version(runner)}"
    command = claude_command(model)
    sources = build_packets(packets, ledger, corpus_root, work, scale)
    for packet in packets:
        save_record(record_dir, packet, sources[packet.key], command, model_label)

    def execute(packet: Packet):
        try:
            return packet, runner(command, work / packet.key), None
        except (OSError, subprocess.SubprocessError) as error:
            return packet, None, str(error)

    failed: list[tuple[str, str]] = []
    unanswered: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for packet, completed, error in pool.map(execute, packets):
            folder = record_dir / packet.key
            if completed is not None:
                (folder / "output.json").write_text(completed.stdout or "", encoding="utf-8")
                if completed.stderr:
                    (folder / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
            try:
                if error:
                    raise CrossError(error)
                answers = parse_output(completed.stdout or "")
            except CrossError as problem:
                failed.append((packet.key, str(problem)))
                continue
            reader = " + ".join(dict.fromkeys(source.reader for source in sources[packet.key]))
            unanswered += apply_answers(items, packet, answers, model_label, reader, today)
    return summarize(items, packets, no_doc, skipped, failed, unanswered)


def apply_record(items: list[dict], record_dir: Path, today: date) -> dict:
    """이미 실행한 기록 폴더의 출력으로 `cross` 칸을 채운다(다시 실행하지 않음). 이미 채운 문항은 그대로 둔다."""
    failed, unanswered, packets = [], [], []
    for packet, model_label, reader, output in read_record(record_dir):
        packets.append(packet)
        try:
            answers = parse_output(output)
        except CrossError as problem:
            failed.append((packet.key, str(problem)))
            continue
        unanswered += apply_answers(items, packet, answers, model_label, reader, today)
    return summarize(items, packets, [], [], failed, unanswered)


def summarize(items, packets, no_doc, skipped, failed, unanswered) -> dict:
    asked = {question["id"] for packet in packets for question in packet.questions}
    counted = asked | {item["id"] for item in no_doc}
    verdicts = Counter(item["cross"]["verdict"] for item in items if item.get("cross") and item["id"] in counted)
    return {"packets": len(packets), "asked": len(asked), "no_doc": len(no_doc), "skipped": skipped,
            "failed": failed, "unanswered": sorted(set(unanswered)), "verdicts": verdicts}
