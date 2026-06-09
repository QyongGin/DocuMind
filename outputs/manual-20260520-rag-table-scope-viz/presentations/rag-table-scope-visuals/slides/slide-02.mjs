import { C, bg, rect, text, kicker, title, note, page, flowNode, connector, metric } from "./helpers.mjs";

export async function slide02(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "진단", "02");
  title(slide, "실패를 검색 문제와 답변 문제로 분리했다");

  flowNode(slide, "질문 실패", 94, 226, 170, 74, C.white, C.line);
  connector(slide, 264, 263, 330, 263, C.muted);
  flowNode(slide, "검색 근거가\n들어왔나?", 330, 206, 178, 112, C.paleBlue, C.blue);
  connector(slide, 508, 263, 590, 202, C.rust);
  connector(slide, 508, 263, 590, 326, C.green);
  flowNode(slide, "아니오\nretrieval 문제", 590, 164, 196, 78, C.paleRust, C.rust);
  flowNode(slide, "예\nanswer 문제 확인", 590, 290, 196, 78, C.paleGreen, C.green);
  connector(slide, 786, 329, 878, 329, C.muted);
  flowNode(slide, "근거는 맞는데\n답변이 틀림", 878, 286, 230, 86, C.white, C.line);

  rect(slide, 92, 430, 1022, 126, C.white, C.line, 1, true);
  text(slide, "관찰 결과", 122, 454, 120, 24, { size: 17, color: C.blue, bold: true, fill: C.white });
  text(slide, "trace(검색 근거)는 8/8로 통과했는데 answer(답변)는 2~3/8까지 떨어졌다.\n즉 ChromaDB가 아예 못 찾은 문제가 아니라, EXAONE이 받은 문맥에서 정답 행·열·카드를 구분하지 못한 문제였다.", 122, 488, 820, 46, {
    size: 19,
    color: C.ink,
    fill: C.white,
  });
  metric(slide, "trace 8/8", "검색 후보 존재", 944, 448, 132, C.blue);

  note(slide, "도구: ai-server/evaluate_rag.py, rag_quality_questions.json, /debug/rag-trace", false);
  page(slide, 2);
  return slide;
}
