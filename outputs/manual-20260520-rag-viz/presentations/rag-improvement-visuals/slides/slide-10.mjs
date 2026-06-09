import { C, bg, rect, text, kicker, title, note, page, metric, connector } from "./helpers.mjs";

function roadmapNode(slide, body, x, y, w) {
  rect(slide, x, y, w, 72, "#20323D", "#526B78", 1, true);
  text(slide, body, x + 16, y + 20, w - 32, 28, {
    size: 19,
    color: C.paper,
    bold: true,
    align: "center",
    fill: "#20323D",
  });
}

export async function slide10(presentation) {
  const slide = presentation.slides.add();
  bg(slide, C.ink);
  kicker(slide, "결론", "10", true);
  title(slide, "결론: RAG 품질은 근거 구조가 결정한다", 76, 92, true);

  metric(slide, "7/8", "대표 평가 통과", 82, 216, 188, C.green);
  metric(slide, "1개", "남은 실패: 약어/모집정원", 300, 216, 238, C.rust);
  metric(slide, "3계층", "raw + table + layout", 568, 216, 226, C.blue);
  metric(slide, "0", "남길 하드코딩 원칙", 824, 216, 208, C.gold);

  roadmapNode(slide, "1. GCP 최신 코드 재색인", 108, 398, 236);
  connector(slide, 344, 434, 420, 434, "#8096A3");
  roadmapNode(slide, "2. 표/범례 평가 케이스 확대", 420, 398, 252);
  connector(slide, 672, 434, 748, 434, "#8096A3");
  roadmapNode(slide, "3. subject catalog로 약어 해결", 748, 398, 252);

  rect(slide, 108, 536, 912, 66, "#1C2B36", "#334753", 1, true);
  text(slide, "다음 발표 메시지", 138, 554, 150, 20, { size: 16, color: C.gold, bold: true, fill: "#1C2B36" });
  text(slide, "DocuMind는 LLM 튜닝보다 먼저 문서 구조화와 평가 루프를 갖춘 RAG 시스템으로 개선되고 있다.", 300, 550, 610, 28, {
    size: 22,
    color: C.paper,
    bold: true,
    fill: "#1C2B36",
  });

  note(slide, "남은 일: 실서버 pull/build, 재업로드 후 evaluate_rag 재실행, table question suite 확장", true);
  page(slide, 10, true);
  return slide;
}
