import { C, arrow, bg, card, footer, header, rect, text } from "./helpers.mjs";

export async function slide04(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  header(slide, 3, "안전한 연결");

  text(slide, "처음부터 실제 검색 흐름에 붙이면 검색 결과, 프롬프트, 사용자 응답이 동시에 흔들릴 수 있었다.", 76, 158, 1040, 28, {
    size: 18,
    color: C.muted,
    transparent: true,
  });

  card(slide, 82, 218, 308, 158, "업로드 흐름", "문서를 쪼개고 합치는 위치\n\n위험: 잘못 붙이면 실제 색인 데이터가 바뀜", C.red, "#FFF5F5");
  card(slide, 486, 218, 308, 158, "인덱스 저장 흐름", "ChromaDB documents를 만드는 위치\n\n위험: 저장값과 metadata가 바뀔 수 있음", C.orange, "#FFF8F0");
  card(slide, 890, 218, 308, 158, "debug trace 출력", "검색 후보를 JSON으로 보여주는 위치\n\n장점: 관찰만 하고 runtime 영향 없음", C.green, "#F1FBF4");

  arrow(slide, 390, 298, 486, 298, "#7A8190");
  arrow(slide, 794, 298, 890, 298, "#7A8190");

  rect(slide, 138, 462, 1004, 116, C.navy, C.navy, 0, true);
  text(slide, "핵심 판단", 174, 488, 170, 24, {
    size: 18,
    color: C.yellow,
    bold: true,
    transparent: true,
  });
  text(slide, "data contract는 먼저 /debug/rag-trace에서만 관찰했다.\n그래서 업로드, 저장, 검색 순위, LLM prompt, /query 응답을 바꾸지 않고 구조를 검증했다.", 174, 520, 890, 42, {
    size: 18,
    color: C.paper,
    bold: true,
    align: "center",
    transparent: true,
  });

  footer(slide, 4);
  return slide;
}
