"""대장 ID 규칙: 원래 주소에서 나오는 `사이트/종류/번호`.

다시 수집해도 같은 ID가 나와야 이어 받기와 중복 검사가 된다.
본교 K2Web 사이트 ID `kr`은 사람이 읽기 쉽게 `www`로 적는다.
"""

import hashlib
import re


def site_prefix(site_id: str) -> str:
    return "www" if site_id == "kr" else site_id


def page_id(site_id: str, menu_no: str | int) -> str:
    return f"{site_prefix(site_id)}/page/{menu_no}"


def post_id(site_id: str, board_no: str | int, seq: str | int) -> str:
    return f"{site_prefix(site_id)}/bbs/{board_no}/{seq}"


def attach_id(post_doc_id: str, file_seq: str | int) -> str:
    return f"{post_doc_id}/a{file_seq}"


def viewer_id(site_id: str, viewer_no: str | int, index: int = 1) -> str:
    """모집요강 뷰어 파일. 첫 파일(출력용)은 `ipsi/viewer/13`, 둘째부터 `ipsi/viewer/14/f2`."""
    base = f"{site_prefix(site_id)}/viewer/{viewer_no}"
    return base if index == 1 else f"{base}/f{index}"


def file_id(site_id: str, filename: str) -> str:
    """정적 파일(예: 입시결과 PDF)은 확장자를 뺀 파일 이름으로 ID를 만든다."""
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return f"{site_prefix(site_id)}/file/{stem}"


def faq_id(site_id: str, board_no: str | int, question: str) -> str:
    """FAQ는 글 번호가 없어서 공백을 뺀 질문 글의 해시로 ID를 만든다."""
    normalized = re.sub(r"\s+", "", question)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{site_prefix(site_id)}/faq/{board_no}/q{digest}"


def raw_relpath(doc_id: str, kind: str, ext: str) -> str:
    """corpus `raw/` 아래 저장 경로. 글 본문은 첨부와 같은 폴더의 `body.html`."""
    if kind == "post":
        return f"{doc_id}/body.html"
    return f"{doc_id}.{ext}"
