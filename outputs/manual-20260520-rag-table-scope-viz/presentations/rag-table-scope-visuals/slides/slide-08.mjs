import { C, bg, rect, text, kicker, title, note, page, pill, connector } from "./helpers.mjs";

function miniTable(slide, x, y) {
  rect(slide, x, y, 390, 44, C.blue, C.blue, 0);
  text(slide, "결석일수", x + 14, y + 12, 86, 18, { size: 14, color: C.white, bold: true, fill: C.blue });
  ["0일", "1일", "2일", "3일", "10일 이상"].forEach((v, i) => {
    text(slide, v, x + 102 + i * 56, y + 12, 52, 18, { size: 14, color: C.white, bold: true, align: "center", fill: C.blue });
  });
  rect(slide, x, y + 44, 390, 44, C.white, C.blue, 1);
  text(slide, "가산점", x + 14, y + 56, 86, 18, { size: 14, color: C.blue, bold: true, fill: C.white });
  ["20점", "18점", "16점", "14점", "0점"].forEach((v, i) => {
    text(slide, v, x + 102 + i * 56, y + 56, 52, 18, { size: 14, color: C.ink, align: "center", fill: C.white });
  });
}

export async function slide08(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "Table/evidence", "08");
  title(slide, "표는 ‘보이는 모양’을 사실 문장으로 바꿨다");

  rect(slide, 84, 188, 450, 352, C.white, C.line, 1, true);
  text(slide, "범례형 표", 116, 216, 130, 22, { size: 18, color: C.green, bold: true, fill: C.white });
  text(slide, "♣ 표시: 4년제 학사학위(전공심화)과정 개설 학과", 116, 254, 360, 24, {
    size: 18,
    color: C.ink,
    bold: true,
    fill: C.white,
  });
  text(slide, "로봇자동화공학과 ♣\n자동차공학과 ♣\n전기공학과 ♣\n컴퓨터정보공학과 ♣\n컴퓨터시스템공학과 ♣\n...", 132, 304, 250, 120, {
    size: 20,
    color: C.ink,
    fill: C.white,
  });
  pill(slide, "legend aggregate", 116, 466, 160, C.green);
  text(slide, "조건을 만족하는 row subject를 모아 목록 근거로 만든다.", 292, 468, 190, 34, {
    size: 15,
    color: C.muted,
    fill: C.white,
  });

  rect(slide, 614, 188, 500, 352, C.white, C.line, 1, true);
  text(slide, "라벨-값 표", 646, 216, 130, 22, { size: 18, color: C.rust, bold: true, fill: C.white });
  miniTable(slide, 648, 262);
  connector(slide, 842, 366, 842, 424, C.rust);
  rect(slide, 670, 424, 350, 48, C.paleRust, C.rust, 1, true);
  text(slide, "출결상황 가산점: 0일=20점; 1일=18점; 2일=16점; ...", 690, 438, 302, 18, {
    size: 15,
    color: C.ink,
    bold: true,
    fill: C.paleRust,
  });
  pill(slide, "label-value evidence", 646, 492, 182, C.rust);

  note(slide, "로컬 smoke test 완료: legend aggregate, label-value table evidence. GCP 실문서 재색인 검증은 다음 단계.", false);
  page(slide, 8);
  return slide;
}
