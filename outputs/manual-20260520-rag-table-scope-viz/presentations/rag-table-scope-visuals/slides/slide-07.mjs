import { C, bg, rect, text, kicker, title, note, page, pill, connector } from "./helpers.mjs";

export async function slide07(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "Layout layer", "07");
  title(slide, "2단 카드 문제는 layout 보조 청크로 풀었다");

  rect(slide, 92, 196, 468, 300, C.white, C.line, 1, true);
  text(slide, "PDF 51페이지 구조", 126, 222, 220, 24, { size: 18, color: C.blue, bold: true, fill: C.white });
  rect(slide, 128, 274, 176, 142, C.paleBlue, C.blue, 2, true);
  rect(slide, 346, 274, 176, 142, C.paleRust, C.rust, 2, true);
  text(slide, "컴퓨터정보공학과\n주요 교과목\n주요 취업처", 150, 304, 132, 64, {
    size: 18,
    color: C.ink,
    bold: true,
    align: "center",
    fill: C.paleBlue,
  });
  text(slide, "컴퓨터시스템공학과\n주요 교과목\n주요 취업처", 368, 304, 132, 64, {
    size: 18,
    color: C.ink,
    bold: true,
    align: "center",
    fill: C.paleRust,
  });
  text(slide, "raw Markdown에서는 좌우가 한 문단처럼 섞였다.", 132, 444, 360, 28, {
    size: 17,
    color: C.muted,
    fill: C.white,
  });

  connector(slide, 560, 346, 664, 346, C.muted);
  rect(slide, 664, 190, 500, 312, C.white, C.line, 1, true);
  text(slide, "layout_parallel evidence", 700, 218, 260, 24, {
    size: 18,
    color: C.green,
    bold: true,
    fill: C.white,
  });
  text(slide, "열 1 제목: 컴퓨터정보공학과\n- 주요 교과목: 자료구조, 데이터베이스...\n- 주요 취업처: 레인보우 브레인, 퀸텟시스템즈...\n\n열 2 제목: 컴퓨터시스템공학과\n- 주요 교과목: C/C++/자바...\n- 주요 취업처: 제너셈, 와이즈와이어즈...", 706, 260, 390, 154, {
    size: 17,
    color: C.ink,
    fill: C.white,
  });
  pill(slide, "bbox coverage 1.0", 704, 438, 160, C.blue);
  pill(slide, "confidence gate", 882, 438, 154, C.green);

  note(slide, "구현 원칙: 기존 raw chunk를 지우지 않고, 안전 판정된 layout 보조 청크를 추가했다.", false);
  page(slide, 7);
  return slide;
}
