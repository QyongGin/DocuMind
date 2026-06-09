import { C, bg, rect, text, kicker, title, note, page } from "./helpers.mjs";

function decision(slide, y, trial, why, result, color) {
  rect(slide, 92, y, 258, 62, C.white, C.line, 1);
  rect(slide, 350, y, 420, 62, "#FAFAF7", C.line, 1);
  rect(slide, 770, y, 350, 62, color, C.line, 1);
  text(slide, trial, 112, y + 16, 212, 24, { size: 18, color: C.ink, bold: true, fill: C.white });
  text(slide, why, 372, y + 14, 356, 30, { size: 15, color: C.muted, fill: "#FAFAF7" });
  text(slide, result, 792, y + 14, 280, 30, { size: 15, color: C.ink, bold: true, fill: color });
}

export async function slide09(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "되돌림", "09");
  title(slide, "잘 맞아도 하드코딩이면 되돌렸다");

  rect(slide, 92, 188, 1028, 42, C.blue, C.blue, 0);
  text(slide, "시도", 112, 200, 120, 16, { size: 14, color: C.white, bold: true, fill: C.blue });
  text(slide, "위험", 372, 200, 120, 16, { size: 14, color: C.white, bold: true, fill: C.blue });
  text(slide, "결정", 792, 200, 120, 16, { size: 14, color: C.white, bold: true, fill: C.blue });

  decision(slide, 230, "card_fact 1차", "특정 학과 소개 카드에만 강하게 맞는 구조", "general layout layer로 전환", C.paleBlue);
  decision(slide, 292, "문자열 split", "‘주요 취업처 주요 취업처’ 같은 패턴 의존", "parser/layout 기반으로 대체", C.paleGreen);
  decision(slide, 354, "employment intent", "취업처 단어를 intent로 박으면 범용성이 낮음", "동적 label 후보 방식으로 정리", C.paleRust);
  decision(slide, 416, "약어 alias", "컴정 같은 약어는 문서별/학교별 충돌 가능", "이번 범위에서 revert, 후속 subject catalog로 분리", "#F5ECD8");

  rect(slide, 132, 540, 940, 68, C.white, C.line, 1, true);
  text(slide, "원칙", 162, 562, 66, 22, { size: 18, color: C.rust, bold: true, fill: C.white });
  text(slide, "특정 모집요강을 맞추는 코드가 아니라, 다른 표와 문서에도 적용되는 구조화 규칙만 남긴다.", 238, 558, 730, 28, {
    size: 23,
    color: C.ink,
    bold: true,
    fill: C.white,
  });

  note(slide, "되돌린 예: 색인 주어 기반 약어 확장 적용 커밋은 Revert 처리. 약어는 다음 이슈로 분리.", false);
  page(slide, 9);
  return slide;
}
