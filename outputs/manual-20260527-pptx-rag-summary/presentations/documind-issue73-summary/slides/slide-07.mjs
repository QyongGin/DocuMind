import { C, bg, card, footer, header, rect, text } from "./helpers.mjs";

export async function slide07(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  header(slide, 6, "일관성 보강");

  text(slide, "source_blocks는 원문 출처의 기준이 되기 때문에, documents와 상태가 어긋나면 더 위험해진다.", 76, 158, 1040, 28, {
    size: 18,
    color: C.muted,
    transparent: true,
  });

  card(slide, 84, 214, 346, 142, "1. 저장 순서 보정", "documents 저장이 성공한 뒤에 source_blocks를 저장하도록 순서를 바꿨다.", C.blue, "#F2F8FF");
  card(slide, 466, 214, 346, 142, "2. 실패 시 rollback", "둘 중 하나라도 실패하면 같은 document_id 기준으로 양쪽 상태를 맞춘다.", C.green, "#F1FBF4");
  card(slide, 848, 214, 346, 142, "3. 삭제 실패 보상", "한쪽 삭제만 성공해서 DB와 검색 인덱스가 어긋나는 위험을 줄였다.", C.orange, "#FFF8F0");

  rect(slide, 120, 426, 1040, 100, C.navy, C.navy, 0, true);
  text(slide, "왜 중요한가?", 158, 452, 170, 24, {
    size: 20,
    color: C.yellow,
    bold: true,
    transparent: true,
  });
  text(slide, "검색 인덱스는 지워졌는데 DB 문서는 active로 남거나, 원문 출처만 남는 상태를 막아야 운영에서 신뢰할 수 있다.", 322, 450, 750, 28, {
    size: 21,
    color: C.paper,
    bold: true,
    align: "center",
    transparent: true,
  });

  rect(slide, 202, 586, 876, 44, "#F7F4ED", "#E7DED0", 1, true);
  text(slide, "PR #85 merge 완료 · merge commit 010ef056 · #73의 첫 runtime 저장 연결", 230, 600, 820, 16, {
    size: 15,
    color: C.ink,
    bold: true,
    align: "center",
    transparent: true,
  });

  footer(slide, 7);
  return slide;
}
