import { C, arrow, bg, footer, header, rect, text } from "./helpers.mjs";

function collection(slide, x, y, title, body, color) {
  rect(slide, x, y, 270, 150, "#FAFBFD", color, 2, true);
  text(slide, title, x + 20, y + 20, 230, 28, {
    size: 22,
    color,
    bold: true,
    align: "center",
    transparent: true,
  });
  text(slide, body, x + 24, y + 62, 222, 54, {
    size: 14,
    color: C.muted,
    align: "center",
    transparent: true,
  });
}

export async function slide06(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  header(slide, 5, "원문 저장소");

  text(slide, "PR #85에서 검색용 documents collection은 유지하고, 원문 출처 전용 source_blocks collection을 추가했다.", 76, 158, 1040, 28, {
    size: 18,
    color: C.muted,
    transparent: true,
  });

  rect(slide, 92, 246, 188, 92, C.navy, C.navy, 0, true);
  text(slide, "업로드된\nraw chunk", 122, 266, 128, 42, {
    size: 22,
    color: C.paper,
    bold: true,
    align: "center",
    transparent: true,
  });

  arrow(slide, 280, 292, 400, 292, "#6A7280");
  collection(slide, 400, 214, "documents", "embedding 검색에 쓰는 기존 collection\n검색 순위와 prompt는 유지", C.blue);
  collection(slide, 400, 392, "source_blocks", "사용자에게 보여줄 원문 조각을 id 기반으로 보관", C.green);
  arrow(slide, 280, 292, 400, 468, "#6A7280");

  rect(slide, 742, 280, 360, 178, "#F8FAFC", "#D9DEE8", 1, true);
  text(slide, "연결 metadata", 778, 306, 160, 24, { size: 20, color: C.ink, bold: true, transparent: true });
  text(slide, "source_block_id\nsource_lookup_id", 780, 348, 230, 56, {
    size: 24,
    color: C.blue,
    bold: true,
    transparent: true,
  });
  text(slide, "검색 후보에서 원문 SourceBlock을 다시 찾는 키", 780, 418, 260, 20, {
    size: 13,
    color: C.muted,
    transparent: true,
  });
  arrow(slide, 670, 288, 742, 352, "#6A7280");
  arrow(slide, 670, 468, 742, 404, "#6A7280");

  rect(slide, 160, 566, 960, 48, "#EAF7EE", "#B6E6C4", 1, true);
  text(slide, "결과: 이제 검색 chunk와 사용자 출처 원문을 같은 document_id 안에서 따로 관리할 수 있다.", 190, 581, 900, 18, {
    size: 17,
    color: C.ink,
    bold: true,
    align: "center",
    transparent: true,
  });

  footer(slide, 6);
  return slide;
}
