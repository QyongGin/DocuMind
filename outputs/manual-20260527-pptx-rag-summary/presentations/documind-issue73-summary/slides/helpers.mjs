export const C = {
  navy: "#18304B",
  navy2: "#213B5C",
  blue: "#0B83E6",
  cyan: "#22C7D7",
  green: "#3BCB6D",
  orange: "#FF914D",
  yellow: "#FFE66D",
  red: "#E25B5B",
  ink: "#161B2C",
  muted: "#5F6572",
  line: "#C9CED8",
  panel: "#F6F8FB",
  panel2: "#EEF6FF",
  paper: "#FFFFFF",
  cream: "#F7F4ED",
};

export function bg(slide, color = C.paper) {
  slide.background.fill = { type: "solid", color };
}

export function rect(slide, x, y, w, h, fill = C.paper, line = C.line, width = 1, radius = false) {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    position: { left: x, top: y, width: w, height: h },
    fill: { type: "solid", color: fill },
    line: { style: "solid", fill: line, width },
  });
}

export function ellipse(slide, x, y, w, h, fill = C.paper, line = C.line, width = 1) {
  return slide.shapes.add({
    geometry: "ellipse",
    position: { left: x, top: y, width, height: h },
    fill: { type: "solid", color: fill, transparency: fill === "none" ? 100 : 0 },
    line: { style: "solid", fill: line, width },
  });
}

export function text(slide, body, x, y, w, h, opts = {}) {
  const shapeOptions = {
    geometry: "rect",
    position: { left: x, top: y, width: w, height: h },
  };
  if (!opts.transparent) {
    shapeOptions.fill = { type: "solid", color: opts.fill || "FFFFFF" };
    shapeOptions.line = { style: "solid", fill: opts.line || opts.fill || "FFFFFF", width: opts.lineWidth ?? 0 };
  }
  const shape = slide.shapes.add(shapeOptions);
  shape.text.style = {
    fontSize: opts.size || 24,
    color: opts.color || C.ink,
    typeface: opts.font || "Apple SD Gothic Neo",
    bold: opts.bold || false,
    alignment: opts.align || "left",
    verticalAlignment: opts.valign || "top",
  };
  shape.text = body;
  return shape;
}

export function header(slide, index, title) {
  rect(slide, 0, 0, 1280, 126, C.navy, C.navy, 0);
  rect(slide, 0, 126, 1280, 6, C.blue, C.blue, 0);
  text(slide, String(index).padStart(2, "0"), 58, 48, 72, 40, {
    size: 28,
    color: C.blue,
    bold: true,
    transparent: true,
    align: "center",
  });
  text(slide, title, 150, 38, 980, 58, {
    size: 42,
    color: C.paper,
    bold: true,
    transparent: true,
  });
}

export function footer(slide, page, note = "DocuMind #73 RAG 구조 개선 작업 정리") {
  text(slide, note, 44, 688, 700, 18, { size: 10, color: C.muted, transparent: true });
  text(slide, String(page).padStart(2, "0"), 1155, 686, 38, 18, { size: 10, color: C.muted, transparent: true, align: "right" });
}

export function pill(slide, label, x, y, w, color, textColor = C.paper) {
  rect(slide, x, y, w, 32, color, color, 0, true);
  text(slide, label, x + 10, y + 7, w - 20, 18, {
    size: 13,
    color: textColor,
    bold: true,
    align: "center",
    transparent: true,
  });
}

export function card(slide, x, y, w, h, title, body, accent = C.blue, fill = C.panel) {
  rect(slide, x, y, w, h, fill, "#D9DEE8", 1, true);
  rect(slide, x, y, 6, h, accent, accent, 0, false);
  text(slide, title, x + 20, y + 16, w - 36, 24, {
    size: 17,
    color: C.ink,
    bold: true,
    transparent: true,
  });
  text(slide, body, x + 20, y + 48, w - 36, h - 58, {
    size: 13,
    color: C.muted,
    transparent: true,
  });
}

export function line(slide, x, y, w, color = C.line, h = 2) {
  rect(slide, x, y, w, h, color, color, 0);
}

export function vline(slide, x, y, h, color = C.line, w = 2) {
  rect(slide, x, y, w, h, color, color, 0);
}

export function arrow(slide, x1, y1, x2, y2, color = C.ink) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  if (Math.abs(dy) <= 2) {
    line(slide, x1, y1, Math.max(1, dx - 9), color, 2);
    rect(slide, x2 - 9, y1 - 5, 9, 10, color, color, 0);
    return;
  }
  if (Math.abs(dx) <= 2) {
    vline(slide, x1, y1, Math.max(1, dy - 9), color, 2);
    rect(slide, x1 - 5, y2 - 9, 10, 9, color, color, 0);
    return;
  }
  const midX = x1 + dx / 2;
  line(slide, x1, y1, midX - x1, color, 2);
  vline(slide, midX, Math.min(y1, y2), Math.abs(dy), color, 2);
  line(slide, midX, y2, x2 - midX - 9, color, 2);
  rect(slide, x2 - 9, y2 - 5, 9, 10, color, color, 0);
}

export function tag(slide, label, x, y, color = C.blue) {
  rect(slide, x, y, 86, 24, color, color, 0, true);
  text(slide, label, x + 8, y + 5, 70, 12, { size: 10, color: C.paper, bold: true, align: "center", transparent: true });
}
