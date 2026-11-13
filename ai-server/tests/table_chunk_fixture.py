"""표 청크 후보 테스트용 지어낸 학교(가나대학) PDF 두 쪽: 쪽 글(마크다운)과 OpenDataLoader JSON 모양."""

PAGE_1 = """## 가나대학 모집인원

|계열|모집단위|수시1차| |
|---|---|---|---|
| | |일반고|특성화고|
|공학|가나기계과 ★|30|5|
| |나다전자과|25|4|

★ 표시: 야간 과정을 함께 운영하는 학과
※ 모집인원은 사정에 따라 바뀔 수 있음

## 가나대학 학사 안내
가나대학 휴학 신청은 학기 시작 전까지 포털에서 할 수 있다."""

PAGE_2 = """|계열|모집단위|수시1차| |
|---|---|---|---|
| | |일반고|특성화고|
|인문|라마경영과|40|6|
|인문|바사회계과|20|3|"""


def cell(r, c, text, rs=1, cs=1):
    return {"type": "table cell", "row number": r, "column number": c, "row span": rs, "column span": cs,
            "kids": [{"type": "paragraph", "content": text}] if text else []}


HEADER = [cell(1, 1, "계열", rs=2), cell(1, 2, "모집단위", rs=2), cell(1, 3, "수시1차", cs=2),
          cell(2, 3, "일반고"), cell(2, 4, "특성화고")]

JSON_1 = {"page number": 1, "kids": [
    {"type": "heading", "content": "가나대학 모집인원", "bounding box": [50, 710, 300, 724]},
    {"type": "table", "id": 10, "next table id": 11, "page number": 1, "bounding box": [50, 400, 550, 700],
     "rows": [{"row number": 1, "cells": HEADER[:3]}, {"row number": 2, "cells": HEADER[3:]},
              {"row number": 3, "cells": [cell(3, 1, "공학", rs=2), cell(3, 2, "가나기계과 ★"), cell(3, 3, "30"), cell(3, 4, "5")]},
              {"row number": 4, "cells": [cell(4, 2, "나다전자과"), cell(4, 3, "25"), cell(4, 4, "4")]}]},
    {"type": "paragraph", "content": "★ 표시: 야간 과정을 함께 운영하는 학과", "bounding box": [50, 380, 300, 392]},
    {"type": "paragraph", "content": "※ 모집인원은 사정에 따라 바뀔 수 있음", "bounding box": [50, 364, 300, 376]},
    {"type": "paragraph", "content": "가나대학 휴학 신청은 학기 시작 전까지 포털에서 할 수 있다.", "bounding box": [50, 200, 500, 212]},
]}

JSON_2 = {"page number": 2, "kids": [
    {"type": "table", "id": 11, "previous table id": 10, "page number": 2, "bounding box": [50, 500, 550, 760],
     "rows": [{"row number": 1, "cells": HEADER[:3]}, {"row number": 2, "cells": HEADER[3:]},
              {"row number": 3, "cells": [cell(3, 1, "인문", rs=2), cell(3, 2, "라마경영과"), cell(3, 3, "40"), cell(3, 4, "6")]},
              {"row number": 4, "cells": [cell(4, 2, "바사회계과"), cell(4, 3, "20"), cell(4, 4, "3")]}]},
]}

# 긴 표(조각으로 나뉘는 표): 보강 머리글 줄이 있는 모집인원 표 60행
LONG_TABLE = "\n".join(
    ["|계열|모집단위|수시1차| |", "|---|---|---|---|", "| | |일반고|특성화고|"]
    + [f"|공학|가나{n:02d}과|{20 + n}|{n % 7}|" for n in range(60)]
)
