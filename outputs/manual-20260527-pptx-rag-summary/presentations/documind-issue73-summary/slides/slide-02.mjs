import { C, arrow, bg, card, footer, header, rect, text } from "./helpers.mjs";

const roles = [
  ["parser 결과", 116, 198, C.cyan],
  ["검색 대상", 396, 198, C.blue],
  ["LLM 근거", 676, 198, C.green],
  ["사용자 출처", 956, 198, C.orange],
  ["table_fact 부모", 256, 438, C.yellow],
  ["debug trace 후보", 816, 438, C.red],
];

export async function slide02(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  header(slide, 1, "문제 정의");

  text(slide, "기존 구조의 위험", 70, 160, 280, 28, {
    size: 22,
    color: C.ink,
    bold: true,
    transparent: true,
  });
  text(slide, "검색을 잘하려고 chunk에 제목·이전 문맥·표 요약을 붙이면, 같은 chunk가 사용자에게는 실제 원문처럼 보일 수 있다.", 70, 194, 1040, 34, {
    size: 18,
    color: C.muted,
    transparent: true,
  });

  rect(slide, 492, 330, 296, 104, C.navy, C.navy, 0, true);
  text(slide, "기존 chunk", 522, 352, 236, 30, {
    size: 28,
    color: C.paper,
    bold: true,
    align: "center",
    transparent: true,
  });
  text(slide, "검색용 내용과 원문 출처가 섞임", 522, 394, 236, 20, {
    size: 13,
    color: "#C8D3DE",
    align: "center",
    transparent: true,
  });

  for (const [label, x, y, color] of roles) {
    card(slide, x, y + 42, 208, 72, label, "같은 텍스트를 여러 목적에 사용", color, C.panel);
    arrow(slide, x + 104, y + 114, 640, 330, "#7A8190");
  }

  rect(slide, 104, 598, 1072, 54, "#FFF8DD", "#F2C94C", 1, true);
  text(slide, "따라서 #73의 핵심은 검색에 쓰는 내용과 사용자에게 보여줄 원문 출처를 분리하는 것이다.", 130, 615, 1020, 22, {
    size: 18,
    color: C.ink,
    bold: true,
    align: "center",
    transparent: true,
  });

  footer(slide, 2);
  return slide;
}
