import { C, bg, rect, text, kicker, title, note, page, connector, pill } from "./helpers.mjs";

function cell(slide, body, x, y, w, h, fill, opts = {}) {
  rect(slide, x, y, w, h, fill, opts.line || C.line, 1);
  text(slide, body, x + 8, y + 8, w - 16, h - 14, {
    size: opts.size || 14,
    color: opts.color || C.ink,
    bold: opts.bold || false,
    align: opts.align || "center",
    valign: "middle",
    fill,
  });
}

function miniTable(slide, label, heading, rows, x, y, w, color) {
  rect(slide, x, y, w, 178, C.white, C.line, 1, true);
  pill(slide, label, x + 18, y + 16, 128, color);
  text(slide, heading, x + 18, y + 58, w - 36, 26, {
    size: 18,
    bold: true,
    color,
    fill: C.white,
  });
  const tableY = y + 96;
  cell(slide, rows[0][0], x + 18, tableY, 104, 34, color, {
    color: C.white,
    bold: true,
    size: 13,
  });
  cell(slide, rows[0][1], x + 122, tableY, w - 140, 34, color, {
    color: C.white,
    bold: true,
    size: 13,
  });
  cell(slide, rows[1][0], x + 18, tableY + 34, 104, 38, "#F7F7F5", {
    bold: true,
  });
  cell(slide, rows[1][1], x + 122, tableY + 34, w - 140, 38, "#F7F7F5", {
    size: 13,
  });
}

export async function slide09(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "table scope", "09");
  title(slide, "셀 값만 보면 ‘20점’의 의미를 잃는다", 76, 64);
  text(slide, "같은 점수처럼 보여도 표 주변 제목과 머리글이 다르면 완전히 다른 사실이다.", 58, 158, 880, 32, {
    size: 20,
    color: C.muted,
    fill: C.paper,
  });

  miniTable(
    slide,
    "표 A",
    "다. 학기등급 점수 환산 방법",
    [
      ["산출 석차등급", "200점 환산식"],
      ["1.000000등급", "25 × (9 - 산출 석차등급)"],
    ],
    72,
    220,
    430,
    C.blue,
  );
  miniTable(
    slide,
    "표 B",
    "라. 출결상황에 따른 가산점",
    [
      ["결석일수", "0일 · 1일 · 2일 · 3일 · 10일 이상"],
      ["가산점", "20점 · 18점 · 16점 · 14점 · 0점"],
    ],
    778,
    220,
    430,
    C.green,
  );

  rect(slide, 528, 242, 224, 146, C.paleRust, C.rust, 1, true);
  text(slide, "기존 문제", 554, 262, 172, 22, {
    size: 15,
    color: C.rust,
    bold: true,
    align: "center",
    fill: C.paleRust,
  });
  text(slide, "가산점 = 20점", 552, 300, 176, 28, {
    size: 24,
    color: C.ink,
    bold: true,
    align: "center",
    fill: C.paleRust,
  });
  text(slide, "어느 표의 값인지\n주소가 사라짐", 560, 330, 160, 34, {
    size: 14,
    color: C.muted,
    align: "center",
    fill: C.paleRust,
  });
  connector(slide, 504, 306, 528, 306, C.rust);
  connector(slide, 752, 306, 778, 306, C.green);

  rect(slide, 142, 462, 996, 92, C.white, C.line, 1, true);
  text(slide, "개선 방향", 176, 490, 128, 26, {
    size: 17,
    color: C.blue,
    bold: true,
    fill: C.white,
  });
  text(
    slide,
    "값 하나만 저장하지 않고 section heading(주변 제목) + table header(표 머리글) + row label(행 라벨) + column label(열 라벨)을 함께 묶어 evidence(근거)로 만든다.",
    316,
    482,
    760,
    48,
    { size: 19, color: C.ink, bold: true, fill: C.white },
  );

  note(slide, "핵심: 표 질의는 셀 값보다 표의 문맥 주소가 먼저다. 이 주소가 없으면 EXAONE은 맞는 값도 일반론으로 흐릴 수 있다.");
  page(slide, 9);
  return slide;
}
