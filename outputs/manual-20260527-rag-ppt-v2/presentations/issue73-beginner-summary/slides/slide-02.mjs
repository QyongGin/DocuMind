import { C, arrow, pill, rect, slideBase, step, text } from "./helpers.mjs";

export async function slide02(presentation) {
  const slide = slideBase(presentation, "해결 방향", 2);

  text(slide, "해결은 정답을 외우게 하는 것이 아니라 역할을 먼저 나누는 것부터 시작했다", 36, 92, 875, 32, {
    size: 21,
    color: C.ink,
    bold: true,
    fill: C.white,
  });
  text(
    slide,
    "역할을 나누지 않으면 문제를 고치는 듯 보여도 결국 같은 문서 조각에 임시 표시만 계속 붙게 된다.",
    36,
    127,
    870,
    26,
    { size: 13.2, color: C.muted, fill: C.white },
  );

  rect(slide, 36, 174, 578, 256, C.pale, C.line, 1.2, true);
  pill(slide, "바꾼 구조", 60, 196, 98, C.blue);

  step(slide, 1, "문서 읽기", "글·표·목록을 작은 단위로 읽음", 66, 242, 210, C.blue);
  step(slide, 2, "원문 보관", "사용자에게 보여줄 출처는 원문 그대로 저장", 348, 242, 226, C.green);
  step(slide, 3, "검색용 내용", "찾기 쉽도록 제목·문맥을 붙인 문장은 따로 만듦", 66, 340, 236, C.orange);
  step(slide, 4, "답변 근거 선택", "AI에게 넣을 근거만 골라 전달", 348, 340, 226, C.green);

  arrow(slide, 276, 272, 348, 272, C.green);
  arrow(slide, 184, 306, 184, 340, C.orange);
  arrow(slide, 302, 370, 348, 370, C.green);
  arrow(slide, 462, 306, 462, 340, C.muted);
  text(slide, "원문 주소로 다시 연결", 388, 312, 150, 15, {
    size: 8.8,
    color: C.muted,
    align: "center",
    fill: C.pale,
  });

  rect(slide, 642, 174, 282, 256, C.white, C.line, 1.2, true);
  pill(slide, "이번 주 실제 작업", 666, 196, 128, C.orange);

  const items = [
    ["1", "역할 이름표 설계", "무엇을 읽고, 찾고, 보여줄지 먼저 분리"],
    ["2", "먼저 관찰", "답변은 바꾸지 않고 진단 화면에만 표시"],
    ["3", "오염 감지", "숫자·금액이 제목처럼 들어오면 의심 표시"],
    ["4", "원문 저장 준비", "검색 결과가 원문을 다시 찾도록 연결"],
  ];
  let y = 236;
  for (const [n, title, body] of items) {
    rect(slide, 666, y, 234, 42, C.pale, C.line, 1, true);
    rect(slide, 678, y + 10, 22, 22, C.blue, C.blue, 0, true);
    text(slide, n, 678, y + 14, 22, 12, {
      size: 8.6,
      color: C.white,
      bold: true,
      align: "center",
      fill: C.blue,
    });
    text(slide, title, 710, y + 7, 170, 13, {
      size: 10.2,
      color: C.ink,
      bold: true,
      fill: C.pale,
    });
    text(slide, body, 710, y + 23, 178, 12, {
      size: 7.8,
      color: C.muted,
      fill: C.pale,
    });
    y += 49;
  }

  rect(slide, 36, 450, 888, 36, C.paleYellow, "#F2C94C", 1.2, true);
  text(
    slide,
    "결론: 특정 질문을 맞히는 임시 수정이 아니라, 근거가 어디서 왔는지 설명 가능한 구조로 바꾸는 중이다.",
    70,
    460,
    820,
    16,
    { size: 13.4, color: C.ink, bold: true, align: "center", fill: C.paleYellow },
  );

  return slide;
}
