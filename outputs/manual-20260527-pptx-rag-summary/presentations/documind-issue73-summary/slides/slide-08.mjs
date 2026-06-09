import { C, arrow, bg, footer, header, rect, text } from "./helpers.mjs";

function step(slide, n, title, body, x, y, color, active = false) {
  rect(slide, x, y, 230, 116, active ? "#EAF7EE" : "#FAFBFD", color, active ? 3 : 1.5, true);
  rect(slide, x + 16, y + 16, 30, 30, color, color, 0, true);
  text(slide, String(n), x + 16, y + 21, 30, 12, {
    size: 13,
    color: C.paper,
    bold: true,
    align: "center",
    transparent: true,
  });
  text(slide, title, x + 58, y + 16, 150, 20, {
    size: 16,
    color,
    bold: true,
    transparent: true,
  });
  text(slide, body, x + 22, y + 54, 186, 38, {
    size: 13,
    color: C.muted,
    align: "center",
    transparent: true,
  });
}

export async function slide08(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  header(slide, 7, "다음 단계");

  text(slide, "지금까지는 RAG 품질을 바로 올린 것이 아니라, 품질 개선을 안전하게 넣을 수 있는 구조를 만든 단계다.", 76, 158, 1040, 28, {
    size: 18,
    color: C.muted,
    transparent: true,
  });

  step(slide, 1, "완료", "data contract 정의\ntrace preview 검증", 74, 216, C.blue);
  step(slide, 2, "완료", "SourceBlock store\n원문 저장 연결", 344, 216, C.green);
  step(slide, 3, "다음", "/query 출처를\n원문 기준으로 전환", 614, 216, C.orange, true);
  step(slide, 4, "후속", "검색용 chunk를\n실제 indexing에 연결", 884, 216, C.cyan);

  arrow(slide, 304, 274, 344, 274, "#7A8190");
  arrow(slide, 574, 274, 614, 274, "#7A8190");
  arrow(slide, 844, 274, 884, 274, "#7A8190");

  rect(slide, 122, 426, 1036, 108, C.navy, C.navy, 0, true);
  text(slide, "다음 PR의 범위", 160, 450, 220, 24, {
    size: 20,
    color: C.yellow,
    bold: true,
    transparent: true,
  });
  text(slide, "검색 순위, documents 저장값, LLM prompt는 그대로 둔다.\n사용자에게 보이는 출처 미리보기만 source_blocks 원문으로 바꾼다.", 160, 486, 860, 34, {
    size: 18,
    color: C.paper,
    bold: true,
    align: "center",
    transparent: true,
  });

  rect(slide, 160, 586, 960, 44, "#EEF6FF", "#C9E5FF", 1, true);
  text(slide, "면접 한 문장: 검색용 텍스트와 사용자 출처 원문을 분리해, 품질 개선이 출처 신뢰성을 해치지 않도록 구조를 바꿨습니다.", 188, 598, 904, 18, {
    size: 15,
    color: C.ink,
    bold: true,
    align: "center",
    transparent: true,
  });

  footer(slide, 8);
  return slide;
}
