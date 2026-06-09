import { C, arrow, card, pill, rect, slideBase, smallCard, text } from "./helpers.mjs";

export async function slide01(presentation) {
  const slide = slideBase(presentation, "문제 정의", 1);

  text(slide, "기존 문제는 AI가 가끔 틀리는 정도가 아니었다", 36, 92, 850, 32, {
    size: 22,
    color: C.ink,
    bold: true,
    fill: C.white,
  });
  text(
    slide,
    "문서를 잘게 나눈 뒤, 그 한 조각이 검색·답변 근거·사용자 출처·표 판단을 모두 맡으면서 문서 안의 관계가 사라졌다.",
    36,
    127,
    870,
    26,
    { size: 13.2, color: C.muted, fill: C.white },
  );

  rect(slide, 52, 181, 856, 244, C.pale, C.line, 1.2, true);
  pill(slide, "기존 흐름", 76, 204, 96, C.blue);

  rect(slide, 390, 246, 210, 92, C.navy, C.navy, 1.2, true);
  text(slide, "기존 문서 조각", 416, 272, 158, 20, {
    size: 18,
    color: C.white,
    bold: true,
    align: "center",
    fill: C.navy,
  });
  text(slide, "검색용 내용과 원문 출처가 같은 곳에 들어감", 416, 301, 158, 18, {
    size: 9.8,
    color: "#D9E6F2",
    align: "center",
    fill: C.navy,
  });

  smallCard(slide, 92, 218, 170, 62, "문서를 읽은 결과", "파서가 문서에서 뽑은 글", "#2EC4D6");
  smallCard(slide, 302, 166, 166, 62, "검색할 내용", "질문과 비교할 문장", C.blue);
  smallCard(slide, 610, 166, 166, 62, "AI 답변 근거", "답변 만들 때 참고", C.green);
  smallCard(slide, 700, 282, 166, 62, "사용자 출처", "답변 아래에 보여줄 근거", C.orange);
  smallCard(slide, 148, 332, 184, 62, "표와 목록 판단", "행·열·범례 관계 확인", "#FFD84D");

  arrow(slide, 262, 248, 386, 292, C.muted);
  arrow(slide, 386, 206, 456, 244, C.muted);
  arrow(slide, 602, 292, 704, 312, C.muted);
  arrow(slide, 602, 292, 616, 206, C.muted);
  arrow(slide, 332, 362, 390, 320, C.muted);

  rect(slide, 52, 444, 856, 42, C.paleYellow, "#F2C94C", 1.2, true);
  text(
    slide,
    "따라서 #73의 핵심은 검색에 쓰는 내용과 사용자에게 보여줄 원문 출처를 분리하는 것이다.",
    96,
    456,
    780,
    19,
    { size: 15, color: C.ink, bold: true, align: "center", fill: C.paleYellow },
  );

  text(slide, "왜 위험한가?", 674, 361, 160, 18, {
    size: 12.2,
    color: C.red,
    bold: true,
    fill: C.pale,
  });
  text(
    slide,
    "제목·표·본문·출처가 섞이면\n어느 단계에서 틀렸는지 분리해 보기 어렵다.",
    674,
    382,
    190,
    32,
    { size: 9.4, color: C.muted, fill: C.pale },
  );

  return slide;
}
