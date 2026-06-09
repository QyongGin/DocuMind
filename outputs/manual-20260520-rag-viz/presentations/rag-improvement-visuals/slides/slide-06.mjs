import { C, bg, rect, text, kicker, title, note, page, metric, flowNode, connector } from "./helpers.mjs";

export async function slide06(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "평가 루프", "06");
  title(slide, "보이지 않던 품질을 숫자와 trace로 보이게 했다");

  flowNode(slide, "check_chunks.py\n저장 청크/품질 진단", 78, 214, 216, 86, C.paleBlue, C.blue);
  connector(slide, 294, 257, 360, 257, C.muted);
  flowNode(slide, "debug/rag-trace\n검색 단계 추적", 360, 214, 216, 86, C.paleGreen, C.green);
  connector(slide, 576, 257, 642, 257, C.muted);
  flowNode(slide, "evaluate_rag.py\n답변/출처 자동 검사", 642, 214, 230, 86, C.paleRust, C.rust);
  connector(slide, 872, 257, 938, 257, C.muted);
  flowNode(slide, "JSON/CSV output\n실패 상세 확인", 938, 214, 216, 86, C.white, C.line);

  metric(slide, "raw 121", "관리자 화면 chunk와 일치", 96, 396, 198, C.blue);
  metric(slide, "table 342", "표 구조화 사실", 336, 396, 198, C.green);
  metric(slide, "layout 13", "2단 카드 보조 청크", 576, 396, 198, C.rust);
  metric(slide, "7/8", "대표 평가 통과", 816, 396, 198, C.gold);

  text(slide, "왜 중요했나", 96, 544, 132, 24, { size: 18, color: C.blue, bold: true, fill: C.paper });
  text(slide, "이전에는 “왜 틀렸는지”를 로그에서 감으로 봤다. 지금은 검색 후보, 최종 context, missing keyword, forbidden hit를 분리해서 확인한다.", 236, 540, 780, 32, {
    size: 20,
    color: C.ink,
    fill: C.paper,
  });

  note(slide, "대표 명령: python evaluate_rag.py --include-query --case-id ... --output /tmp/result.json", false);
  page(slide, 6);
  return slide;
}
