import { C, bg, rect, text, kicker, note, page, metric, pill, connector } from "./helpers.mjs";

export async function slide01(presentation) {
  const slide = presentation.slides.add();
  bg(slide, C.ink);

  kicker(slide, "DocuMind RAG 개선", "01", true);
  text(slide, "검색은 됐는데\n답변은 왜 틀렸나?", 72, 108, 620, 142, {
    size: 48,
    color: C.paper,
    bold: true,
    fill: C.ink,
  });
  text(slide, "문제는 모델 크기보다 evidence(근거)의 모양이었다.", 76, 270, 560, 36, {
    size: 22,
    color: "#D5DEE2",
    fill: C.ink,
  });

  metric(slide, "2~3/8", "기존 답변 통과율", 760, 118, 178, C.rust);
  connector(slide, 950, 166, 1000, 166, "#D5DEE2");
  metric(slide, "7/8", "개선 후 대표 평가", 1012, 118, 178, C.green);
  metric(slide, "8/8", "검색 trace는 계속 통과", 760, 250, 430, C.blue);

  rect(slide, 76, 384, 1110, 180, "#1C2B36", "#334753", 1, true);
  text(slide, "이번 작업의 한 줄 결론", 106, 412, 250, 28, {
    size: 18,
    color: C.gold,
    bold: true,
    fill: "#1C2B36",
  });
  text(slide, "LLM을 바꾸기 전에 PDF를 LLM이 읽을 수 있는 구조로 바꿨다.\n표, 범례, 2단 카드, 라벨-값 관계를 보존하고 질문에 맞는 근거만 압축해 전달했다.", 106, 455, 930, 76, {
    size: 28,
    color: C.paper,
    bold: true,
    fill: "#1C2B36",
  });
  pill(slide, "evaluate", 104, 586, 120, C.blue);
  pill(slide, "chunk 진단", 242, 586, 128, C.green);
  pill(slide, "layout", 388, 586, 102, C.gold);
  pill(slide, "table_fact", 508, 586, 128, C.rust);
  pill(slide, "evidence focus", 654, 586, 168, C.blue);

  note(slide, "범위: 이슈 #18 RAG 평가 루프, PDF layout/table 청킹, 근거 압축, 실패 시도와 되돌림까지", true);
  page(slide, 1, true);
  return slide;
}
