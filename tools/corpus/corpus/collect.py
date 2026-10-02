"""수집 순서와 대장 기록. 네트워크는 `PoliteSession`을 거쳐서만 쓴다.

단위(페이지 하나, 글 하나와 그 첨부, FAQ 게시판 하나 …)를 끝까지 처리하면 `visits`에 적는다.
중간에 멈추면(오류 연속, 사용자 중단) 다음 실행이 적힌 단위를 건너뛰고 이어 받는다.
"""

import hashlib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from . import extract, ids, pii, scope, sites
from .ledger import Ledger
from .polite import PoliteSession, RobotsDisallowed

TARGETS = ("pages", "regulations", "faq", "ipsi", "depts", "notices")
EMPTY_FILE_NOTE = "빈 파일(0바이트): 학교 사이트가 내용 없이 내려준다"
NO_CONTENT_NOTE = "본문 글·그림·첨부 없음(동영상·링크만 있는 글 등)"
UNREADABLE_NOTE_PREFIXES = ("글자 추출 실패", "암호 또는 배포용")


@dataclass
class Fetched:
    url: str
    content: bytes
    headers: dict

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


@dataclass
class Counts:
    saved: int = 0
    held: int = 0
    duplicate: int = 0
    skipped: int = 0
    empty: int = 0
    failed: int = 0


def measure_file(fmt: str, path: Path, html: str | None = None) -> tuple[dict, str | None, str | None]:
    """(대장 칸, 추출한 글 — 못 읽으면 None, 비고)."""
    empty = {"text_chars": None, "table_count": None, "image_heavy": None}
    try:
        if fmt == "html":
            chars, tables, images, text = extract.html_metrics(html if html is not None else path.read_text("utf-8"))
            return {"text_chars": chars, "table_count": tables, "image_heavy": int(extract.image_heavy_html(chars, images))}, text, None
        if fmt == "pdf":
            chars, pages, text = extract.pdf_metrics(str(path))
            return {"text_chars": chars, "table_count": None, "image_heavy": int(extract.image_heavy_pdf(chars, pages))}, text, f"{pages}쪽"
        if fmt == "hwp":
            chars, tables, text, note = extract.hwp_metrics(str(path))
            if note:
                return empty, None, note
            return {"text_chars": chars, "table_count": tables, "image_heavy": 0}, text, None
        if fmt == "hwpx":
            chars, tables, text = extract.hwpx_metrics(str(path))
            return {"text_chars": chars, "table_count": tables, "image_heavy": 0}, text, None
    except Exception as error:  # 손상된 파일 등: 대장에 남기고 계속한다
        return empty, None, f"글자 추출 실패: {type(error).__name__}"
    return empty, None, None


def three_years_before(today: date) -> date:
    try:
        return today.replace(year=today.year - scope.NOTICE_YEARS)
    except ValueError:  # 2월 29일
        return today.replace(year=today.year - scope.NOTICE_YEARS, day=28)


class Collector:
    def __init__(self, session: PoliteSession, ledger: Ledger, root: str | Path, today: date,
                 cutoff: date | None = None, log=print):
        self.session = session
        self.ledger = ledger
        self.root = Path(root)
        self.today = today
        self.cutoff = cutoff or three_years_before(today)
        self.log = log
        self.counts = Counts()
        self._unit_failed = False
        self._main_sitemap: Fetched | None = None

    # ---- 실행 ----

    def run(self, targets=TARGETS) -> Counts:
        steps = {
            "pages": self.main_pages,
            "regulations": self.regulations,
            "faq": self.faqs,
            "ipsi": self.ipsi,
            "depts": self.depts,
            "notices": self.notices,
        }
        for target in targets:
            self.log(f"== {target}")
            steps[target]()
        return self.counts

    # ---- 네트워크 ----

    def fail(self, url: str, stage: str, error: str, doc_id: str | None = None) -> None:
        self.ledger.add_failure(url, stage, error, doc_id)
        self.counts.failed += 1
        self._unit_failed = True
        self.log(f"  실패 [{stage}] {url}: {error}")

    def fetch(self, url: str, referer: str | None = None, doc_id: str | None = None,
              stage: str = "fetch", limit: int | None = None) -> Fetched | None:
        try:
            response = self.session.get(url, referer=referer, stream=limit is not None)
        except RobotsDisallowed:
            self.fail(url, "robots", "robots.txt가 막은 주소라 요청하지 않음", doc_id)
            return None
        except requests.RequestException as error:
            self.fail(url, stage, f"{type(error).__name__}: {error}", doc_id)
            return None
        try:
            if response.status_code != 200:
                self.fail(url, stage, f"HTTP {response.status_code}", doc_id)
                return None
            if limit is not None:
                declared = int(response.headers.get("Content-Length") or 0)
                if declared > limit:
                    self.fail(url, stage, f"파일이 너무 큼({declared} bytes)", doc_id)
                    return None
                chunks, size = [], 0
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        self.fail(url, stage, f"파일이 너무 큼(>{limit} bytes)", doc_id)
                        return None
                    chunks.append(chunk)
                content = b"".join(chunks)
            else:
                content = response.content
            return Fetched(response.url or url, content, dict(response.headers))
        finally:
            response.close()

    def main_sitemap(self) -> Fetched | None:
        if self._main_sitemap is None:
            self._main_sitemap = self.fetch(scope.MAIN_SITEMAP, stage="sitemap")
        return self._main_sitemap

    # ---- 대장 기록 ----

    def base_row(self, doc_id: str, kind: str, site: str, url: str, title: str, fmt: str, **extra) -> dict:
        row = {
            "doc_id": doc_id, "kind": kind, "site": ids.site_prefix(site), "url": url, "title": title,
            "format": fmt, "collected_at": self.today.isoformat(), "visibility": "공개",
        }
        row.update({key: value for key, value in extra.items() if value is not None})
        return row

    def approved_pending(self, doc_id: str) -> bool:
        """1차 보류였다가 사람이 '통과'로 확인했지만 아직 받지 않은 행."""
        row = self.ledger.get(doc_id)
        return bool(row and row["reviewed"] and row["pii_status"] == "통과" and not row["file_path"])

    def already_have(self, doc_id: str) -> bool:
        """받았거나, 보류·제외로 받지 않기로 한 행. 사람이 1차 보류를 풀어 준 행만 다시 받는다."""
        row = self.ledger.get(doc_id)
        return bool(row) and (bool(row["file_path"]) or not self.approved_pending(doc_id))

    def unit_done(self, unit: str, doc_ids: list[str] = ()) -> bool:
        return self.ledger.visited(unit) and not any(self.approved_pending(doc_id) for doc_id in doc_ids)

    def hold(self, row: dict, keyword: str, note: str | None = None) -> None:
        """개인정보 1차: 내려받지 않고 보류 행만 만든다."""
        row.update(pii_status="보류", pii_reason=f"1차 제목·파일명: {keyword}", index_status="제외")
        if note:
            row["notes"] = note
        self.ledger.upsert(row)
        self.counts.held += 1
        self.log(f"  보류(1차 {keyword}) {row['doc_id']} {row['title']}")

    def store(self, doc_id: str, kind: str, ext: str, data: bytes) -> dict:
        """원본 저장. 같은 내용(SHA256)이 이미 있으면 새로 쓰지 않고 그 파일을 가리킨다."""
        digest = hashlib.sha256(data).hexdigest()
        twin = self.ledger.find_by_sha256(digest)
        if twin and twin["doc_id"] != doc_id and twin["file_path"]:
            return {"file_path": twin["file_path"], "sha256": digest, "size_bytes": len(data), "twin": twin["doc_id"]}
        relpath = Path("raw") / ids.raw_relpath(doc_id, kind, ext)
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"file_path": relpath.as_posix(), "sha256": digest, "size_bytes": len(data), "twin": None}

    def save_and_record(self, row: dict, data: bytes, ext: str, html: str | None = None,
                        force_hold: str | None = None, no_content: bool = False) -> None:
        stored = self.store(row["doc_id"], row["kind"], ext, data)
        row.update(file_path=stored["file_path"], sha256=stored["sha256"], size_bytes=stored["size_bytes"])
        measured, text, note = measure_file(row["format"], self.root / stored["file_path"], html)
        row.update(measured)
        notes = [part for part in (row.get("notes"), note) if part]

        existing = self.ledger.get(row["doc_id"])
        if existing and existing["reviewed"]:
            # 사람이 확인한 칸은 두고, 새로 받은 내용에서 2차 패턴이 나오면 다시 확인 대기로
            row.pop("notes", None)
            self.ledger.upsert(row)
            hits = pii.text_hits(text)
            if hits:
                self.ledger.reopen(row["doc_id"], "2차 본문(확인 뒤 받은 내용): " + ", ".join(hits))
                self.counts.held += 1
            self.counts.saved += 1
            return

        if text is None:
            status, reason = "보류", f"2차 검사 못 함(형식 {row['format']}{', ' + note if note else ''})"
        else:
            status, reason = pii.judge(row["title"], text)
        if status == "통과" and force_hold:
            status, reason = "보류", force_hold
        row["pii_status"], row["pii_reason"] = status, reason
        if stored["twin"]:
            notes.append(f"내용 중복: {stored['twin']}")
            row["index_status"] = "제외"
            self.counts.duplicate += 1
        elif no_content:
            notes.append(NO_CONTENT_NOTE)
            row["index_status"] = "제외"
        else:
            row["index_status"] = extract.index_status(status, row.get("valid_until"), self.today)
        row["notes"] = " / ".join(notes) or None
        self.ledger.upsert(row)
        if status == "보류":
            self.counts.held += 1
            self.log(f"  보류({reason}) {row['doc_id']}")
        self.counts.saved += 1

    def download_row(self, row: dict, url: str, referer: str | None, fallback_name: str,
                     force_hold: str | None = None, on_name=None) -> bool:
        fetched = self.fetch(url, referer=referer, doc_id=row["doc_id"], stage=row["kind"], limit=scope.MAX_DOWNLOAD_BYTES)
        if fetched is None:
            return False
        name = sites.disposition_filename(fetched.headers.get("Content-Disposition")) or fallback_name
        if name.lower().endswith(".tmp"):  # 뷰어 임시 파일 이름은 뜻이 없다
            name = fallback_name
        if on_name:
            on_name(row, name)
        if not fetched.content:
            # 학교 사이트가 내용 없이 내려주는 첨부(실측 4개). 원본은 남기지 않고 행만 기록한다
            row.update(size_bytes=0, text_chars=0, notes=EMPTY_FILE_NOTE, pii_status="통과", index_status="제외")
            self.ledger.upsert(row)
            self.counts.empty += 1
            return True
        row["format"] = extract.sniff_format(name, fetched.content[:128])
        ext = row["format"] if row["format"] not in ("image", "etc") else extract.file_ext(name)
        self.save_and_record(row, fetched.content, ext, force_hold=force_hold)
        return True

    # ---- 안내 페이지 ----

    def page(self, url: str, site: str, menu_no: str, name: str, *, fixed_topic: str | None = None,
             section_topic: str | None = None, group_prefix: str = "안내", title_suffix: str = "",
             aliases: str | None = None, people: bool = False) -> None:
        doc_id = ids.page_id(site, menu_no)
        if self.unit_done(doc_id, [doc_id]):
            self.counts.skipped += 1
            return
        self._unit_failed = False
        keyword = pii.title_hit(name)
        if keyword and not self.approved_pending(doc_id):
            self.hold(self.base_row(doc_id, "page", site, url, name + title_suffix, "html"), keyword)
            self.ledger.mark_visited(doc_id)
            return
        fetched = self.fetch(url, doc_id=doc_id, stage="page")
        if fetched is None:
            return
        body = extract.page_body(fetched.text)
        chars, _, images, _ = extract.html_metrics(body.html) if body.html else (0, 0, 0, "")
        if chars < scope.PAGE_MIN_CHARS and images == 0:
            # 글도 그림도 없는 기능·목록 페이지. 그림 위주 페이지(로드맵 등)는 image_heavy 행으로 남긴다
            self.counts.empty += 1
            self.ledger.mark_visited(doc_id)
            return
        core = sites.page_title(fetched.text) or name
        title = core + title_suffix
        row = self.base_row(
            doc_id, "page", site, url, title, "html", posted_at=body.updated_at,
            topic=extract.suggest_topic(title, fixed_topic, section_topic), valid_until="until_replaced",
            aliases=aliases, group_id=f"{group_prefix}:{extract.group_name(core)}",
        )
        self.save_and_record(row, body.html.encode("utf-8"), "html", html=body.html,
                             force_hold=scope.PEOPLE_REASON if people else None)
        self.log(f"  페이지 {doc_id} {title} ({chars}자)")
        if not self._unit_failed:
            self.ledger.mark_visited(doc_id)

    def main_pages(self) -> None:
        sitemap = self.main_sitemap()
        if sitemap is None:
            return
        for link in sites.sitemap_links(sitemap.text, sitemap.url):
            if link.site != "kr" or scope.WWW_SKIP_MENU.search(link.name):
                continue
            self.page(link.url, "kr", link.menu_no, link.name,
                      section_topic=scope.SECTION_TOPICS.get(link.section or ""),
                      people=bool(scope.PEOPLE_MENU.search(link.name)))

    # ---- 게시판 ----

    def notice_suggestions(self, board: scope.Board, title: str, posted_at: str | None,
                           valid_basis: str | None = None) -> dict:
        return {
            "topic": extract.suggest_topic(title, board.topic),
            "academic_year": extract.suggest_year(title, posted_at),
            "valid_until": extract.semester_end(valid_basis or posted_at),
            "group_id": f"공지:{extract.group_name(title)}",
        }

    def regulation_suggestions(self, name: str) -> dict:
        return {
            "topic": extract.suggest_topic(name, None, "학사"),
            "revised_at": extract.revised_from_name(name),
            "valid_until": "until_replaced",
            "group_id": f"규정:{extract.group_name(name)}",
        }

    def board(self, board: scope.Board, cutoff: date | None, regulations: bool = False) -> None:
        seen: set[str] = set()
        page_no, total = 1, 1
        while page_no <= total:
            listing = self.fetch(board.list_url(page_no), stage="list")
            if listing is None:
                return
            total = sites.total_pages(listing.text)
            rows = sites.board_rows(listing.text)
            regular = [row for row in rows if not row.pinned]
            for row in rows:
                if row.seq in seen:
                    continue
                seen.add(row.seq)
                if cutoff and row.posted_at and row.posted_at < cutoff.isoformat():
                    continue
                self.post(board, row, listing.url, regulations)
            if not regular:
                return
            if cutoff and all(row.posted_at and row.posted_at < cutoff.isoformat() for row in regular):
                return
            page_no += 1

    def post(self, board: scope.Board, listed: sites.ListRow, referer: str, regulations: bool) -> None:
        doc_id = ids.post_id(board.site, board.board_no, listed.seq)
        children = [row["doc_id"] for row in self.ledger.children(doc_id)]
        # 끝낸 글이라도 대장에 본문 행도 첨부 행도 없으면 다시 처리한다(모든 글은 대장에 남아야 한다)
        represented = self.ledger.has(doc_id) or bool(children)
        if represented and self.unit_done(doc_id, [doc_id, *children]):
            self.counts.skipped += 1
            return
        self._unit_failed = False
        url = board.view_url(listed.seq)
        common = {"board": board.label, "post_no": listed.seq}
        keyword = pii.title_hit(listed.title)
        if keyword and not self.approved_pending(doc_id):
            row = self.base_row(doc_id, "post", board.site, url, listed.title, "html", posted_at=listed.posted_at,
                                **common, **self.notice_suggestions(board, listed.title, listed.posted_at))
            self.hold(row, keyword, note="1차 보류로 글을 열지 않아 첨부 목록을 모름")
            self.ledger.mark_visited(doc_id)
            return
        fetched = self.fetch(url, referer=referer, doc_id=doc_id, stage="post")
        if fetched is None:
            return
        parts = extract.post_parts(fetched.text)
        title = parts.title or listed.title
        posted_at = parts.posted_at or listed.posted_at
        # 유효 기간은 작성일·수정일 중 늦은 날 기준: 고정 공지는 해마다 고쳐 쓰고 작성일은 그대로다
        basis = max(filter(None, [posted_at, parts.modified_at]), default=None)
        suggestions = (self.regulation_suggestions(title) if regulations
                       else self.notice_suggestions(board, title, posted_at, basis))
        existing = self.ledger.get(doc_id)
        has_body = parts.body_chars >= scope.POST_MIN_CHARS or parts.body_images > 0
        if (has_body or not parts.attachments) and not (existing and existing["file_path"]):
            # 그림만 있는 글(포스터)은 image_heavy 행, 글·그림·첨부가 모두 없는 글도 출처로 남긴다(색인 제외)
            row = self.base_row(doc_id, "post", board.site, url, title, "html", posted_at=posted_at,
                                **common, **suggestions)
            self.save_and_record(row, parts.body_html.encode("utf-8"), "html", html=parts.body_html,
                                 no_content=not has_body)
        elif not has_body:
            self.counts.empty += 1  # 본문 없이 첨부만 있는 글: 첨부 행의 parent_id로 남는다
        for attachment in parts.attachments:
            self.attachment(board, doc_id, attachment, fetched.url, posted_at, suggestions, regulations)
        self.log(f"  글 {doc_id} {title} (첨부 {len(parts.attachments)})")
        if not self._unit_failed:
            self.ledger.mark_visited(doc_id)

    def attachment(self, board: scope.Board, post_doc_id: str, attachment: extract.Attachment, referer: str,
                   posted_at: str | None, post_suggestions: dict, regulations: bool) -> None:
        doc_id = ids.attach_id(post_doc_id, attachment.file_seq)
        if self.already_have(doc_id):
            return
        url = urljoin(referer, attachment.href)
        suggestions = dict(post_suggestions)
        if regulations:
            suggestions = self.regulation_suggestions(attachment.name)
        elif extract.revised_from_name(attachment.name):
            suggestions["revised_at"] = extract.revised_from_name(attachment.name)
        row = self.base_row(doc_id, "attach", board.site, url, attachment.name, extract.file_format(attachment.name),
                            parent_id=post_doc_id, board=board.label, post_no=post_doc_id.rsplit("/", 1)[-1],
                            posted_at=posted_at, **suggestions)
        keyword = pii.title_hit(attachment.name)
        if keyword and not self.approved_pending(doc_id):
            self.hold(row, keyword)
            return
        self.download_row(row, url, referer, attachment.name)

    def regulations(self) -> None:
        self.board(scope.REGULATIONS, cutoff=None, regulations=True)

    def notices(self) -> None:
        for board in scope.NOTICE_BOARDS:
            self.log(f"-- {board.label} ({self.cutoff.isoformat()} 이후)")
            self.board(board, cutoff=self.cutoff)

    # ---- FAQ ----

    def faqs(self) -> None:
        for faq in scope.FAQS:
            self.faq(faq)

    def faq(self, faq: scope.Faq) -> None:
        unit = f"faq/{faq.site}/{faq.board_no}"
        prefix = ids.faq_id(faq.site, faq.board_no, "").rsplit("/", 1)[0] + "/"
        if self.ledger.visited(unit) and not self.ledger.approved_pending_under(prefix):
            self.counts.skipped += 1
            return
        self._unit_failed = False
        first = self.fetch(faq.menu_url, stage="faq")
        if first is None:
            return
        pages = [first]
        for page_no in range(2, sites.total_pages(first.text) + 1):
            fetched = self.fetch(faq.list_url(page_no), referer=faq.menu_url, stage="faq")
            if fetched is not None:
                pages.append(fetched)
        used: set[str] = set()
        for page in pages:
            items = sites.faq_items(page.text)
            if not items:
                self.fail(page.url, "faq", "FAQ 문답을 읽지 못함(화면 구조 확인 필요)")
            for item in items:
                doc_id = ids.faq_id(faq.site, faq.board_no, item.question)
                suffix = 2
                while doc_id in used:
                    doc_id = f"{ids.faq_id(faq.site, faq.board_no, item.question)}-{suffix}"
                    suffix += 1
                used.add(doc_id)
                if self.already_have(doc_id):
                    self.counts.skipped += 1
                    continue
                html = extract.faq_document(item.question, item.answer_html)
                row = self.base_row(doc_id, "faq", faq.site, faq.menu_url, item.question, "html",
                                    topic=extract.suggest_topic(item.question, faq.topic),
                                    valid_until="until_replaced", group_id=faq.group)
                keyword = pii.title_hit(item.question)
                if keyword and not self.approved_pending(doc_id):
                    # 답은 목록 화면에 이미 있지만, 1차 규칙대로 원본을 남기지 않는다
                    self.hold(row, keyword)
                    continue
                self.save_and_record(row, html.encode("utf-8"), "html", html=html)
        self.log(f"  FAQ {unit}: {len(used)}건")
        if not self._unit_failed:
            self.ledger.mark_visited(unit)

    # ---- 입학 사이트 ----

    def ipsi(self) -> None:
        for menu_no, track in scope.IPSI_TRACKS.items():
            self.viewer_page(menu_no, track)
        for menu_no in scope.IPSI_PAGES:
            url = f"{scope.IPSI}/ipsi/{menu_no}/subview.do"
            self.page(url, "ipsi", menu_no, f"입학 {menu_no}", fixed_topic="입시", group_prefix="입시")
            self.static_files(url)

    def viewer_page(self, menu_no: str, track: str) -> None:
        unit = f"ipsi/menu/{menu_no}"
        if self.ledger.visited(unit):
            self.counts.skipped += 1
            return
        self._unit_failed = False
        url = f"{scope.IPSI}/ipsi/{menu_no}/subview.do"
        fetched = self.fetch(url, stage="viewer")
        if fetched is None:
            return
        files = sites.viewer_files(fetched.text, fetched.url)
        if not files:
            self.counts.empty += 1
        for item in files:
            doc_id = ids.viewer_id("ipsi", item.viewer_no, item.index)
            if self.already_have(doc_id):
                continue
            fallback = f"{track} {item.label}.pdf"
            group = f"모집요강:{track}" if item.index == 1 else f"모집요강:{track}:{extract.group_name(item.label)}"
            row = self.base_row(doc_id, "viewer", "ipsi", item.url, fallback, "pdf", topic="입시",
                                group_id=group, notes=f"전형: {track} · 링크: {item.label}")
            keyword = pii.title_hit(item.label)
            if keyword and not self.approved_pending(doc_id):
                self.hold(row, keyword)
                continue
            self.download_row(row, item.url, fetched.url, fallback, on_name=viewer_name)
        self.log(f"  모집요강 {track}: 파일 {len(files)}개")
        if not self._unit_failed:
            self.ledger.mark_visited(unit)

    def static_files(self, page_url: str) -> None:
        unit = f"files:{page_url}"
        if self.ledger.visited(unit):
            return
        self._unit_failed = False
        fetched = self.fetch(page_url, stage="files")
        if fetched is None:
            return
        for url, label in sites.static_files(fetched.text, fetched.url):
            filename = urlsplit(url).path.rsplit("/", 1)[-1]
            doc_id = ids.file_id("ipsi", filename)
            if self.already_have(doc_id):
                continue
            year = extract.suggest_year(filename, None)
            title = f"{year}학년도 {label} ({filename})" if year else f"{label} ({filename})"
            row = self.base_row(doc_id, "file", "ipsi", url, title, extract.file_format(filename), topic="입시",
                                academic_year=year, group_id=f"입시결과:{extract.group_name(label)}")
            self.download_row(row, url, fetched.url, filename)
        if not self._unit_failed:
            self.ledger.mark_visited(unit)

    # ---- 학과 사이트 ----

    def depts(self) -> None:
        sitemap = self.main_sitemap()
        if sitemap is None:
            return
        for root_url, name in sites.external_hosts(sitemap.text, sitemap.url, "학과안내"):
            self.dept_site(root_url, name)
        # 본교 주소 아래에 있는 학과·전공심화 페이지(/mecha/, /ee/ …)
        for link in sites.sitemap_links(sitemap.text, sitemap.url):
            if link.section == "학과안내" and link.site not in ("kr", "ipsi", "bootcamp"):
                dept = scope.DEPT_RENAMES.get(link.site, link.name)
                self.page(link.url, link.site, link.menu_no, link.name, fixed_topic="학과·캠퍼스 생활",
                          group_prefix=f"학과:{dept}", title_suffix=f"({dept})")

    def dept_site(self, root_url: str, name: str) -> None:
        unit = f"dept:{root_url}"
        if self.ledger.visited(unit):
            self.counts.skipped += 1
            return
        landing = self.fetch(root_url, stage="dept")
        if landing is None:
            return
        target = urljoin(landing.url, sites.refresh_target(landing.text) or landing.url)
        parts = urlsplit(target)
        site_id = sites.site_id_of(parts.path)
        if site_id is None:
            self.fail(root_url, "dept", "학과 사이트 ID를 찾지 못함")
            return
        sitemap = self.fetch(f"{parts.scheme}://{parts.netloc}/sitemap/{site_id}/siteMapView.do",
                             referer=target, stage="dept")
        if sitemap is None:
            return
        dept = scope.DEPT_RENAMES.get(site_id, name)
        aliases = name if dept != name else None
        before = self.counts.failed
        for link in sites.sitemap_links(sitemap.text, sitemap.url):
            if link.site != site_id or (link.section or "") in scope.DEPT_SKIP_SECTIONS:
                continue
            if scope.DEPT_SKIP_MENU.search(link.name):
                continue
            self.page(link.url, site_id, link.menu_no, link.name, fixed_topic="학과·캠퍼스 생활",
                      group_prefix=f"학과:{dept}", title_suffix=f"({dept})", aliases=aliases,
                      people=bool(scope.PEOPLE_MENU.search(link.name)))
        self.log(f"  학과 {dept} ({site_id})")
        if self.counts.failed == before:
            self.ledger.mark_visited(unit)


def remeasure(ledger: Ledger, root: str | Path, today: date) -> dict:
    """글을 읽지 못한 행을 원본으로 다시 잰다(형식 오인 정정, 새 추출기 추가 뒤). 사람이 확인한 행은 두고, 요청은 보내지 않는다.

    - 내용이 HWPX인 `.hwp`처럼 형식이 바뀌면 파일 확장자도 고친다(같은 파일을 가리키는 행 모두)
    - 0바이트 파일은 지우고 '빈 파일'로 기록한다
    - '2차 검사 못 함'으로 보류했던 행은 읽힌 글로 개인정보를 다시 판단한다
    """
    root = Path(root)
    report = {"checked": 0, "format_fixed": 0, "now_readable": 0, "empty_files": 0}
    doc_ids = [row[0] for row in ledger.con.execute(
        "SELECT doc_id FROM ledger WHERE file_path IS NOT NULL AND text_chars IS NULL AND reviewed = 0 ORDER BY doc_id")]
    for doc_id in doc_ids:
        row = ledger.get(doc_id)  # 앞 행에서 파일 이름이 바뀌었을 수 있다
        if not row or not row["file_path"] or row["text_chars"] is not None:
            continue
        path = root / row["file_path"]
        if not path.exists():
            continue
        report["checked"] += 1
        if path.stat().st_size == 0:
            old_path = row["file_path"]
            in_use = ledger.con.execute(
                "SELECT 1 FROM ledger WHERE file_path = ? AND reviewed = 1", (old_path,)).fetchone()
            if not in_use:  # 사람이 확인한 행이 가리키는 파일은 지우지 않는다
                path.unlink()
            ledger.con.execute(
                "UPDATE ledger SET file_path = NULL, size_bytes = 0, text_chars = 0, notes = ?, pii_status = '통과', "
                "pii_reason = NULL, index_status = '제외' WHERE file_path = ? AND reviewed = 0",
                (EMPTY_FILE_NOTE, old_path),
            )
            ledger.con.commit()
            report["empty_files"] += 1
            continue
        with open(path, "rb") as handle:
            head = handle.read(128)
        fmt = extract.sniff_format(row["title"], head)
        if fmt != row["format"]:
            report["format_fixed"] += 1
            if fmt in ("hwp", "hwpx", "pdf") and path.suffix.lower() != f".{fmt}":
                new_rel = Path(row["file_path"]).with_suffix(f".{fmt}").as_posix()
                path.rename(root / new_rel)
                ledger.con.execute("UPDATE ledger SET file_path = ? WHERE file_path = ?", (new_rel, row["file_path"]))
                ledger.con.commit()
                row["file_path"], path = new_rel, root / new_rel
        measured, text, note = measure_file(fmt, path)
        kept = [part for part in (row["notes"] or "").split(" / ")
                if part and not part.startswith(UNREADABLE_NOTE_PREFIXES)]
        if note:
            kept.insert(0, note)
        update = {"doc_id": doc_id, "format": fmt, **measured, "notes": " / ".join(kept) or None}
        if (row["pii_reason"] or "").startswith("2차 검사 못 함"):
            if text is None:
                update["pii_reason"] = f"2차 검사 못 함(형식 {fmt}{', ' + note if note else ''})"
            else:
                update["pii_status"], update["pii_reason"] = pii.judge(row["title"], text)
                report["now_readable"] += 1
        status = update.get("pii_status", row["pii_status"])
        duplicate = any(part.startswith("내용 중복") for part in kept)
        update["index_status"] = "제외" if duplicate else extract.index_status(status, row["valid_until"], today)
        ledger.upsert(update)
    return report


def viewer_name(row: dict, name: str) -> None:
    """모집요강은 내려받은 파일 이름이 제목이다(예: `2027 신입생 모집요강(출력용).pdf`). 학년도·유효 기간도 거기서."""
    row["title"] = name
    year = extract.suggest_year(name, None)
    if year:
        row.update(academic_year=year, valid_until=f"{year}-02-28")


def counts_dict(counts: Counts) -> dict:
    return asdict(counts)
