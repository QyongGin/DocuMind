import { C, arrow, bg, footer, header, rect, tag, text } from "./helpers.mjs";

function beforeLane(slide) {
  rect(slide, 68, 150, 500, 420, "#F8FAFC", "#D7DDE8", 1, true);
  tag(slide, "BEFORE", 92, 174, C.red);
  text(slide, "한 덩어리 chunk가\n검색·답변·출처를 모두 담당", 94, 214, 420, 64, {
    size: 25,
    color: C.ink,
    bold: true,
    transparent: true,
  });
  rect(slide, 180, 332, 276, 94, C.navy, C.navy, 0, true);
  text(slide, "chunk text", 210, 356, 216, 28, {
    size: 25,
    color: C.paper,
    bold: true,
    align: "center",
    transparent: true,
  });
  text(slide, "원문 + 검색용 보강 + 표 요약", 210, 390, 216, 18, {
    size: 12,
    color: "#C8D3DE",
    align: "center",
    transparent: true,
  });
  text(slide, "문제", 108, 478, 70, 24, { size: 16, color: C.red, bold: true, transparent: true });
  text(slide, "검색을 위해 넣은 가공 문맥이\n사용자 출처처럼 노출될 수 있음", 178, 475, 330, 42, {
    size: 16,
    color: C.muted,
    transparent: true,
  });
}

function afterLane(slide) {
  rect(slide, 618, 150, 594, 420, "#F8FAFC", "#D7DDE8", 1, true);
  tag(slide, "AFTER", 642, 174, C.green);
  text(slide, "역할별 data contract로 분리", 644, 214, 460, 34, {
    size: 27,
    color: C.ink,
    bold: true,
    transparent: true,
  });

  const boxes = [
    ["ParsedBlock", "파서가 읽은 결과", 658, 288, C.cyan],
    ["SourceBlock", "사용자에게 보여줄 원문", 658, 386, C.green],
    ["RetrievalChunk", "검색 엔진에 넣는 텍스트", 936, 288, C.blue],
    ["SelectedContext", "LLM에게 넣는 최종 근거", 936, 386, C.orange],
  ];
  for (const [name, desc, x, y, color] of boxes) {
    rect(slide, x, y, 218, 72, C.paper, color, 2, true);
    text(slide, name, x + 16, y + 14, 186, 22, { size: 18, color, bold: true, align: "center", transparent: true });
    text(slide, desc, x + 16, y + 42, 186, 16, { size: 12, color: C.muted, align: "center", transparent: true });
  }
  arrow(slide, 876, 324, 936, 324, "#6A7280");
  arrow(slide, 876, 422, 936, 422, "#6A7280");
  arrow(slide, 767, 360, 767, 386, "#6A7280");

  rect(slide, 672, 492, 462, 42, "#EAF7EE", "#B6E6C4", 1, true);
  text(slide, "이제 검색 품질을 올려도 원문 출처를 따로 보호할 수 있다.", 694, 504, 420, 18, {
    size: 15,
    color: C.ink,
    bold: true,
    align: "center",
    transparent: true,
  });
}

export async function slide03(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  header(slide, 2, "구조 분리");
  beforeLane(slide);
  afterLane(slide);
  footer(slide, 3);
  return slide;
}
