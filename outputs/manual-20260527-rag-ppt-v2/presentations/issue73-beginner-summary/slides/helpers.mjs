export const C = {
  navy: "#1A2E4A",
  blue: "#0066CC",
  ink: "#172033",
  muted: "#5E6877",
  line: "#D6DEE9",
  pale: "#F6F9FC",
  paleBlue: "#EAF3FF",
  paleGreen: "#EEF8F1",
  paleYellow: "#FFF7D8",
  paleRed: "#FFF3F3",
  orange: "#F28C38",
  green: "#2E9D62",
  red: "#CC4F4F",
  purple: "#6C63D7",
  white: "#FFFFFF",
};

export function slideBase(presentation, title, page) {
  const slide = presentation.slides.add();
  slide.background.fill = { type: "solid", color: C.white };
  rect(slide, 0, 0, 960, 67.2, C.navy, C.navy, 0);
  rect(slide, 0, 67.2, 960, 3.84, C.blue, C.blue, 0);
  text(slide, "03", 33.6, 7.68, 56, 49.92, {
    size: 14.7,
    color: C.blue,
    bold: true,
    align: "left",
    valign: "middle",
    fill: C.navy,
  });
  text(slide, title, 96, 9.6, 760, 46.08, {
    size: 26.7,
    color: C.white,
    bold: true,
    align: "left",
    valign: "middle",
    fill: C.navy,
  });
  text(slide, "DocuMind #73 RAG 구조 개선 작업 정리", 18, 514, 360, 18, {
    size: 9,
    color: C.muted,
    fill: C.white,
  });
  text(slide, String(page).padStart(2, "0"), 915, 514, 28, 18, {
    size: 9,
    color: C.muted,
    align: "right",
    fill: C.white,
  });
  return slide;
}

export function rect(slide, x, y, w, h, fill = C.white, line = C.line, width = 1, radius = false) {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    position: { left: x, top: y, width: w, height: h },
    fill: { type: "solid", color: fill },
    line: { style: "solid", fill: line, width },
  });
}

export function text(slide, body, x, y, w, h, opts = {}) {
  const shape = slide.shapes.add({
    geometry: "rect",
    position: { left: x, top: y, width: w, height: h },
    fill: { type: "solid", color: opts.fill || C.white },
    line: { style: "solid", fill: opts.line || opts.fill || C.white, width: opts.lineWidth ?? 0 },
  });
  shape.text.style = {
    fontSize: opts.size || 18,
    color: opts.color || C.ink,
    typeface: opts.font || "Apple SD Gothic Neo",
    bold: opts.bold || false,
    alignment: opts.align || "left",
    verticalAlignment: opts.valign || "top",
    wrap: "square",
  };
  shape.text = body;
  return shape;
}

export function pill(slide, label, x, y, w, fill = C.blue) {
  rect(slide, x, y, w, 26, fill, fill, 0, true);
  text(slide, label, x + 8, y + 5, w - 16, 16, {
    size: 10.8,
    color: C.white,
    bold: true,
    align: "center",
    fill,
  });
}

export function card(slide, x, y, w, h, title, body, accent = C.blue, fill = C.pale) {
  rect(slide, x, y, w, h, fill, C.line, 1.2, true);
  rect(slide, x, y, 6, h, accent, accent, 0);
  text(slide, title, x + 18, y + 18, w - 36, 22, {
    size: 16,
    color: C.ink,
    bold: true,
    fill,
  });
  text(slide, body, x + 18, y + 48, w - 36, h - 58, {
    size: 11.2,
    color: C.muted,
    fill,
  });
}

export function smallCard(slide, x, y, w, h, title, body, accent = C.blue) {
  rect(slide, x, y, w, h, C.white, C.line, 1, true);
  rect(slide, x, y, 5, h, accent, accent, 0);
  text(slide, title, x + 14, y + 10, w - 28, 18, {
    size: 12.5,
    color: C.ink,
    bold: true,
    fill: C.white,
  });
  text(slide, body, x + 14, y + 32, w - 28, h - 38, {
    size: 9.4,
    color: C.muted,
    fill: C.white,
  });
}

export function arrow(slide, x1, y1, x2, y2, color = C.muted, width = 2.2) {
  slide.shapes.add({
    geometry: "line",
    position: { left: x1, top: y1, width: x2 - x1, height: y2 - y1 },
    line: { style: "solid", fill: color, width, endArrowType: "triangle" },
  });
}

export function step(slide, n, title, body, x, y, w, color) {
  rect(slide, x, y, w, 60, C.white, C.line, 1, true);
  rect(slide, x + 12, y + 14, 32, 32, color, color, 0, true);
  text(slide, String(n), x + 12, y + 20, 32, 16, {
    size: 11,
    color: C.white,
    bold: true,
    align: "center",
    fill: color,
  });
  text(slide, title, x + 56, y + 10, w - 70, 18, {
    size: 12.5,
    color: C.ink,
    bold: true,
    fill: C.white,
  });
  text(slide, body, x + 56, y + 31, w - 70, 20, {
    size: 9.2,
    color: C.muted,
    fill: C.white,
  });
}
