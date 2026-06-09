import { C, bg, rect, text, kicker, title, note, page, connector, pill } from "./helpers.mjs";

function candidate(slide, status, heading, why, x, y, w, color, fill) {
  rect(slide, x, y, w, 122, fill, color, 1, true);
  pill(slide, status, x + 18, y + 16, 96, color);
  text(slide, heading, x + 18, y + 56, w - 36, 26, {
    size: 18,
    color,
    bold: true,
    fill,
  });
  text(slide, why, x + 18, y + 88, w - 36, 26, {
    size: 14,
    color: C.muted,
    fill,
  });
}

export async function slide11(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "context filter", "11");
  title(slide, "질문과 표 주소가 둘 다 맞는 후보만 남긴다", 76, 70);

  rect(slide, 90, 170, 1100, 56, C.ink, C.ink, 0, true);
  text(slide, "사용자 질문", 122, 187, 112, 22, {
    size: 16,
    color: C.gold,
    bold: true,
    fill: C.ink,
  });
  text(slide, "수시모집할 때 출결상황에 따른 가산점 좀 알려줄래?", 260, 184, 760, 26, {
    size: 24,
    color: C.paper,
    bold: true,
    fill: C.ink,
  });

  candidate(
    slide,
    "탈락",
    "나. 학교생활기록부 성적 반영학기",
    "학기 표라서 ‘출결상황’과 맞지 않음",
    82,
    282,
    324,
    C.rust,
    C.paleRust,
  );
  candidate(
    slide,
    "탈락",
    "다. 학기등급 점수 환산 방법",
    "점수 표지만 ‘가산점’ 행이 아님",
    478,
    282,
    324,
    C.rust,
    C.paleRust,
  );
  candidate(
    slide,
    "채택",
    "라. 출결상황에 따른 가산점",
    "표 제목, 행 라벨, 열 라벨이 함께 맞음",
    874,
    282,
    324,
    C.green,
    C.paleGreen,
  );
  connector(slide, 1036, 404, 1036, 454, C.green);

  rect(slide, 740, 454, 420, 108, C.white, C.green, 1, true);
  text(slide, "final context(최종 문맥)", 770, 478, 240, 24, {
    size: 17,
    color: C.green,
    bold: true,
    fill: C.white,
  });
  text(slide, "출결상황에 따른 가산점:\n0일=20점; 1일=18점; 2일=16점; ...", 770, 512, 344, 36, {
    size: 19,
    color: C.ink,
    bold: true,
    fill: C.white,
  });

  rect(slide, 120, 450, 520, 112, C.white, C.line, 1, true);
  text(slide, "하드코딩이 아닌 이유", 150, 482, 180, 22, {
    size: 17,
    color: C.blue,
    bold: true,
    fill: C.white,
  });
  text(slide, "출결/가산점 같은 케이스명을 코드에 박지 않고,\n문서에서 추출한 제목·머리글·행·열 라벨을 질문 단어와 비교한다.", 150, 514, 440, 38, {
    size: 15,
    color: C.ink,
    fill: C.white,
  });

  rect(slide, 226, 604, 828, 42, "#EEF3F5", C.line, 1, true);
  text(slide, "결론", 260, 616, 68, 20, {
    size: 17,
    color: C.rust,
    bold: true,
    fill: "#EEF3F5",
  });
  text(slide, "표 QA는 ‘검색된 청크’보다 ‘질문에 맞는 표 문맥만 남기는 과정’이 정확도를 좌우한다.", 346, 616, 660, 20, {
    size: 19,
    color: C.ink,
    bold: true,
    fill: "#EEF3F5",
  });

  note(slide, "다음 검증: 출결 가산점, 전공심화 범례, 복수 표가 있는 페이지를 별도 평가 케이스로 추가한다.");
  page(slide, 11);
  return slide;
}
