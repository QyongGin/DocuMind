"""표를 살려 마크다운으로 바꾸는 형식 로더(HWP 5.0·HWPX·HTML·DOCX).

본 제품은 한컴의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.

세 형식 모두 표를 칸 주소·병합 수가 있는 격자(`table_grid.TableGrid`)로 만든 뒤 같은 규칙으로 마크다운 표를 낸다.
서비스 업로드와 데이터셋용 색인이 이 코드를 함께 쓴다(학습·서비스 입력을 같게 유지, 설계 6단계 안건 4).
"""

from .errors import UnsupportedDocumentError
from .html_tables import load_docx_markdown, load_html_markdown
from .hwp5 import read_hwp5_blocks
from .hwpx import read_hwpx_blocks
from .table_grid import blocks_to_markdown, separate_adjacent_tables

# 이 패키지가 맡는 확장자. 나머지(pdf·pptx·xlsx)는 main.py의 기존 로더가 맡는다
SUPPORTED_EXTENSIONS = frozenset({"hwp", "hwpx", "html", "htm", "docx"})


def load_markdown(path: str, ext: str) -> str:
    """파일 하나를 마크다운 글로 바꾼다. 읽을 수 없는 문서는 UnsupportedDocumentError를 낸다."""
    ext = ext.lower()
    if ext == "hwp":
        markdown = blocks_to_markdown(read_hwp5_blocks(path))
    elif ext == "hwpx":
        markdown = blocks_to_markdown(read_hwpx_blocks(path))
    elif ext in ("html", "htm"):
        markdown = load_html_markdown(path)
    elif ext == "docx":
        markdown = load_docx_markdown(path)
    else:
        raise ValueError(f"format_loaders가 맡지 않는 확장자입니다: {ext}")
    return separate_adjacent_tables(markdown)


__all__ = ["SUPPORTED_EXTENSIONS", "UnsupportedDocumentError", "load_markdown"]
