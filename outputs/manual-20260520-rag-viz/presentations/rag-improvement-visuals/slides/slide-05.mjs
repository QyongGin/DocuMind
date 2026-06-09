import { C, bg, rect, text, kicker, title, note, page, flowNode, connector } from "./helpers.mjs";

export async function slide05(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "아키텍처", "05");
  title(slide, "검색 단위와 답변 근거를 분리했다");

  flowNode(slide, "PDF 업로드", 62, 214, 130, 62, C.white);
  connector(slide, 192, 245, 248, 245, C.muted);
  flowNode(slide, "Markdown\n+ JSON layout", 248, 200, 156, 90, C.paleBlue, C.blue);
  connector(slide, 404, 245, 456, 245, C.muted);
  flowNode(slide, "cleanup\n빈 표·반복 제거", 456, 200, 158, 90, C.white);

  connector(slide, 614, 245, 696, 160, C.blue);
  connector(slide, 614, 245, 696, 245, C.green);
  connector(slide, 614, 245, 696, 330, C.rust);
  flowNode(slide, "raw chunk", 696, 128, 150, 62, C.paleBlue, C.blue);
  flowNode(slide, "table_fact", 696, 214, 150, 62, C.paleGreen, C.green);
  flowNode(slide, "layout_parallel", 696, 300, 150, 62, C.paleRust, C.rust);

  connector(slide, 846, 160, 920, 245, C.muted);
  connector(slide, 846, 245, 920, 245, C.muted);
  connector(slide, 846, 330, 920, 245, C.muted);
  flowNode(slide, "ChromaDB", 920, 206, 142, 78, "#F5ECD8", C.gold);
  connector(slide, 1062, 245, 1132, 245, C.muted);
  flowNode(slide, "근거\n압축", 1122, 200, 122, 90, C.white, C.line);

  rect(slide, 108, 460, 1030, 106, C.white, C.line, 1, true);
  text(slide, "답변 시에는 전체 원문을 다 넣지 않는다.", 140, 486, 560, 28, {
    size: 24,
    color: C.ink,
    bold: true,
    fill: C.white,
  });
  text(slide, "질문 subject(주어)와 attribute(속성)가 맞는 structured facts(구조화된 사실)를 먼저 넣고, raw chunk는 출처와 보조 근거로 남긴다.", 140, 524, 870, 30, {
    size: 18,
    color: C.muted,
    fill: C.white,
  });

  note(slide, "핵심 파일: ai-server/main.py, ai-server/layout_blocks.py, ai-server/check_chunks.py", false);
  page(slide, 5);
  return slide;
}
