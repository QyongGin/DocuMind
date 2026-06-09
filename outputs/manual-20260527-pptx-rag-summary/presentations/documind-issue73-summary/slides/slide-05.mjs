import { C, arrow, bg, footer, header, pill, rect, text } from "./helpers.mjs";

export async function slide05(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  header(slide, 4, "값과 제목 구분");

  rect(slide, 82, 148, 500, 360, "#FAFBFD", "#D9DEE8", 1, true);
  text(slide, "문제 상황", 112, 176, 160, 24, { size: 20, color: C.red, bold: true, transparent: true });
  text(slide, "표 안의 금액이나 인원수가 제목처럼 저장되면, 검색할 때 엉뚱한 제목처럼 앞에 붙을 수 있다.", 112, 216, 400, 48, {
    size: 17,
    color: C.muted,
    transparent: true,
  });

  rect(slide, 152, 306, 360, 62, "#FFF4F4", C.red, 2, true);
  text(slide, "section_path = [\"423만원\"]", 172, 326, 320, 22, {
    size: 20,
    color: C.red,
    bold: true,
    align: "center",
    transparent: true,
  });
  text(slide, "값처럼 보이는 문자열이 제목 역할을 하려는 상태", 150, 388, 364, 18, {
    size: 13,
    color: C.muted,
    align: "center",
    transparent: true,
  });

  arrow(slide, 582, 328, 698, 328, "#7A8190");

  rect(slide, 698, 148, 500, 360, "#FAFBFD", "#D9DEE8", 1, true);
  text(slide, "일반화된 방어", 728, 176, 180, 24, { size: 20, color: C.green, bold: true, transparent: true });
  text(slide, "특정 금액이나 학과명을 코드에 박지 않았다. 대신 숫자·금액·인원수처럼 “값”으로 보이면 제목 후보에서 조심스럽게 다룬다.", 728, 216, 410, 66, {
    size: 16,
    color: C.muted,
    transparent: true,
  });

  pill(slide, "제목 후보: 의심 상태", 764, 306, 310, C.orange);
  rect(slide, 764, 356, 310, 64, "#EAF7EE", C.green, 1, true);
  text(slide, "검색용 제목으로 붙이지 않고\n원문 그대로 사용", 792, 374, 254, 28, {
    size: 16,
    color: C.ink,
    bold: true,
    align: "center",
    transparent: true,
  });

  rect(slide, 166, 572, 948, 44, "#EEF6FF", "#C9E5FF", 1, true);
  text(slide, "의미: 표 안의 값을 제목으로 착각하지 않게 해서, 출처와 검색 내용이 더 덜 섞이게 만들었다.", 192, 585, 896, 18, {
    size: 16,
    color: C.ink,
    bold: true,
    align: "center",
    transparent: true,
  });

  footer(slide, 5);
  return slide;
}
