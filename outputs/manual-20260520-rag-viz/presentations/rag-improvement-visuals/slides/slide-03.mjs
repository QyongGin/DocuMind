import { C, bg, rect, text, kicker, title, note, page, line } from "./helpers.mjs";

function row(slide, y, label, before, after, tone) {
  rect(slide, 82, y, 270, 64, C.white, C.line, 1);
  rect(slide, 352, y, 360, 64, "#FAFAF7", C.line, 1);
  rect(slide, 712, y, 400, 64, tone, C.line, 1);
  text(slide, label, 104, y + 18, 220, 24, { size: 19, color: C.ink, bold: true, fill: C.white });
  text(slide, before, 374, y + 13, 314, 34, { size: 16, color: C.muted, fill: "#FAFAF7" });
  text(slide, after, 734, y + 13, 342, 34, { size: 16, color: C.ink, bold: true, fill: tone });
}

export async function slide03(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "원인", "03");
  title(slide, "평면 Markdown은 문서 구조를 잃어버렸다");

  text(slide, "기존 parser 결과가 텍스트로는 보이지만, RAG가 필요한 관계는 사라졌다.", 86, 164, 760, 30, {
    size: 21,
    color: C.muted,
    fill: C.paper,
  });
  rect(slide, 82, 218, 1030, 44, C.blue, C.blue, 0);
  text(slide, "문서 구조", 104, 230, 210, 20, { size: 15, color: C.white, bold: true, fill: C.blue });
  text(slide, "기존 raw chunk에서 보인 현상", 374, 230, 300, 20, { size: 15, color: C.white, bold: true, fill: C.blue });
  text(slide, "필요한 보존 방식", 734, 230, 280, 20, { size: 15, color: C.white, bold: true, fill: C.blue });

  row(slide, 262, "2단 학과 카드", "좌우 학과 설명·교과목·취업처가 한 청크에 섞임", "열 제목과 라벨을 붙여 별도 근거 생성", C.paleBlue);
  row(slide, 326, "모집인원 표", "학과명, 모집정원, 수시/정시 열 관계가 약해짐", "table_fact로 행-열-값 문장화", C.paleGreen);
  row(slide, 390, "범례", "♣ 표시 의미와 전체 학과 목록이 분리됨", "범례 조건을 만족하는 row subject 집계", C.paleRust);
  row(slide, 454, "라벨-값 표", "결석일수 0일과 가산점 20점 관계를 못 읽음", "header label과 value label을 쌍으로 압축", "#F5ECD8");

  line(slide, 82, 554, 1030, C.line, 2);
  text(slide, "핵심 판단", 88, 582, 120, 22, { size: 17, color: C.rust, bold: true, fill: C.paper });
  text(slide, "청킹 품질은 글자 수 문제가 아니라 관계 보존 문제였다.", 210, 578, 690, 30, {
    size: 27,
    color: C.ink,
    bold: true,
    fill: C.paper,
  });

  note(slide, "관찰 샘플: 주요 취업처 주요 취업처, 주요 교과목 주요 교과목, MBTI 장식성 짧은 청크", false);
  page(slide, 3);
  return slide;
}
