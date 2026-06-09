import { C, bg, rect, text, kicker, title, note, page, pill } from "./helpers.mjs";

function sourceCard(slide, x, y, head, body, color) {
  rect(slide, x, y, 340, 122, C.white, color, 2, true);
  const pillWidth = head.length > 12 ? 176 : 132;
  pill(slide, head, x + 18, y + 16, pillWidth, color);
  text(slide, body, x + 20, y + 60, 292, 42, { size: 16, color: C.ink, fill: C.white });
}

export async function slide04(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  kicker(slide, "참고 사례", "04");
  title(slide, "대기업 사례도 같은 방향을 말한다");

  sourceCard(slide, 82, 188, "Microsoft", "Document Intelligence RAG: 표와 문단 구조를 보존해 chunking", C.blue);
  sourceCard(slide, 470, 188, "Google", "Document AI Layout Parser: text/table/list 단위와 context-aware chunk", C.green);
  sourceCard(slide, 858, 188, "Anthropic", "Contextual Retrieval: chunk에 문맥을 붙이고 BM25+embedding 결합", C.rust);
  sourceCard(slide, 82, 344, "NVIDIA", "Enterprise RAG Blueprint: text, table, chart, image를 분리 처리", C.gold);
  sourceCard(slide, 470, 344, "IBM Docling", "layout analysis와 table structure recognition을 별도 계층으로 처리", C.blue);
  sourceCard(slide, 858, 344, "Google Grounding", "답변 claim이 facts로 뒷받침되는지 검사", C.green);

  rect(slide, 120, 540, 1010, 72, "#FDFBF6", C.line, 1, true);
  text(slide, "DocuMind 적용 원칙", 150, 558, 190, 24, { size: 17, color: C.blue, bold: true, fill: "#FDFBF6" });
  text(slide, "문서를 평면 텍스트로만 저장하지 않고, layout(배치)과 table structure(표 구조)를 검색 가능한 근거로 분리한다.", 350, 554, 690, 30, {
    size: 22,
    color: C.ink,
    bold: true,
    fill: "#FDFBF6",
  });

  note(slide, "참고: Azure AI Document Intelligence, Google Document AI/Vertex AI Search, Anthropic Contextual Retrieval, NVIDIA RAG Blueprint, IBM Docling", false);
  page(slide, 4);
  return slide;
}
