import { C, bg, line, rect, text } from "./helpers.mjs";

export async function slide01(presentation) {
  const slide = presentation.slides.add();
  bg(slide, C.navy);

  rect(slide, 0, 0, 10, 720, C.blue, C.blue, 0);
  rect(slide, 1018, 0, 3, 136, C.blue, C.blue, 0);
  rect(slide, 1118, 280, 3, 288, C.blue, C.blue, 0);
  rect(slide, 1056, 172, 142, 2, "#0B579A", "#0B579A", 0);
  rect(slide, 1056, 616, 142, 2, "#0B579A", "#0B579A", 0);

  text(slide, "DocuMind", 70, 215, 620, 76, {
    size: 60,
    color: C.paper,
    bold: true,
    transparent: true,
  });
  text(slide, "RAG 구조 개선 작업 정리", 74, 324, 660, 42, {
    size: 32,
    color: C.blue,
    bold: true,
    transparent: true,
  });
  text(slide, "문서 구조를 보존하는 검색·출처 분리 설계", 74, 372, 640, 30, {
    size: 20,
    color: "#C5CED8",
    transparent: true,
  });
  line(slide, 74, 442, 710, "#C5CED8", 2);
  text(slide, "#73 · Data Contract → Trace 검증 → SourceBlock runtime 연결", 74, 472, 760, 26, {
    size: 18,
    color: "#C5CED8",
    transparent: true,
  });
  text(slide, "202244092 김용진   |   2026.05", 74, 515, 640, 22, {
    size: 15,
    color: "#AEB9C4",
    transparent: true,
  });

  return slide;
}
