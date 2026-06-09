import { C, bg, rect, text, kicker, title, note, page, connector, pill } from "./helpers.mjs";

function scopeNode(slide, label, value, x, y, w, color) {
  rect(slide, x, y, w, 104, C.white, color, 1, true);
  pill(slide, label, x + 18, y + 16, 124, color);
  text(slide, value, x + 18, y + 58, w - 36, 30, {
    size: 18,
    color: C.ink,
    bold: true,
    align: "center",
    valign: "middle",
    fill: C.white,
  });
}

export async function slide10(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "scope chain", "10");
  title(slide, "근거는 표의 주소까지 붙여서 만든다", 76, 64);
  text(slide, "표에서 뽑은 셀 값을 바로 답변에 넣지 않고, 그 셀이 어디에서 나온 값인지 계층을 같이 만든다.", 58, 158, 940, 32, {
    size: 20,
    color: C.muted,
    fill: C.paper,
  });

  scopeNode(slide, "section", "VI. 성적 반영방법\n> 수시모집", 62, 230, 190, C.blue);
  scopeNode(slide, "table title", "라. 출결상황에 따른\n가산점", 292, 230, 210, C.green);
  scopeNode(slide, "header", "결석일수", 542, 230, 150, C.gold);
  scopeNode(slide, "row label", "가산점", 732, 230, 150, C.rust);
  scopeNode(slide, "column/value", "0일=20점\n1일=18점", 922, 230, 220, C.blue);

  connector(slide, 252, 282, 292, 282, C.muted);
  connector(slide, 502, 282, 542, 282, C.muted);
  connector(slide, 692, 282, 732, 282, C.muted);
  connector(slide, 882, 282, 922, 282, C.muted);

  rect(slide, 132, 414, 1018, 146, C.white, C.line, 1, true);
  text(slide, "structured fact(구조화된 사실)", 168, 440, 360, 26, {
    size: 18,
    color: C.green,
    bold: true,
    fill: C.white,
  });
  text(
    slide,
    "출결상황에 따른 가산점: 0일=20점; 1일=18점; 2일=16점; 3일=14점; 4일=12점; 5일=10점; ...; 10일 이상=0점이다.",
    168,
    482,
    760,
    42,
    { size: 19, color: C.ink, bold: true, fill: C.white },
  );
  rect(slide, 998, 438, 104, 86, C.paleGreen, C.green, 1, true);
  text(slide, "LLM에는\n이 문장만\n우선 전달", 1014, 456, 72, 52, {
    size: 16,
    color: C.green,
    bold: true,
    align: "center",
    valign: "middle",
    fill: C.paleGreen,
  });

  rect(slide, 176, 594, 928, 44, "#EEF3F5", C.line, 1, true);
  text(slide, "효과", 210, 606, 76, 22, {
    size: 17,
    color: C.blue,
    bold: true,
    fill: "#EEF3F5",
  });
  text(slide, "질문이 표 전체를 묻더라도 답변 모델은 셀 값이 아니라 ‘표 제목이 붙은 사실 문장’을 읽게 된다.", 300, 606, 760, 22, {
    size: 19,
    color: C.ink,
    bold: true,
    fill: "#EEF3F5",
  });

  note(slide, "구현 위치: ai-server/main.py의 table evidence 생성 단계. 고정 케이스 문자열이 아니라 문서에서 추출된 표 라벨을 조합한다.");
  page(slide, 10);
  return slide;
}
