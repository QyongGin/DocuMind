export const C = {
  paper: "#F6F1E8",
  ink: "#13202A",
  muted: "#4B5963",
  blue: "#0B5D7E",
  green: "#2A7A5E",
  rust: "#C7553A",
  gold: "#C8952C",
  paleBlue: "#DDEBF2",
  paleGreen: "#DDECE3",
  paleRust: "#F1DED8",
  line: "#B9C1C7",
  white: "#FFFFFF",
};

export function bg(slide, color = C.paper) {
  slide.background.fill = { type: "solid", color };
}

export function rect(slide, x, y, w, h, fill = C.white, line = C.line, width = 1, radius = false) {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    position: { left: x, top: y, width: w, height: h },
    fill: { type: "solid", color: fill },
    line: { style: "solid", fill: line, width },
  });
}

export function ellipse(slide, x, y, w, h, fill = C.white, line = C.line, width = 1) {
  return slide.shapes.add({
    geometry: "ellipse",
    position: { left: x, top: y, width: w, height: h },
    fill: { type: "solid", color: fill },
    line: { style: "solid", fill: line, width },
  });
}

export function text(slide, body, x, y, w, h, opts = {}) {
  const shape = slide.shapes.add({
    geometry: "rect",
    position: { left: x, top: y, width: w, height: h },
    fill: { type: "solid", color: opts.fill || C.paper },
    line: { style: "solid", fill: opts.line || opts.fill || C.paper, width: opts.lineWidth ?? 0 },
  });
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

export function kicker(slide, label, index = "01", dark = false) {
  const color = dark ? C.paper : C.blue;
  rect(slide, 56, 42, 28, 6, color, color, 0);
  text(slide, `${index} / ${label.toUpperCase()}`, 94, 30, 360, 32, {
    size: 13,
    color,
    bold: true,
    fill: dark ? C.ink : C.paper,
  });
}

export function title(slide, body, y = 76, h = 90, dark = false) {
  return text(slide, body, 56, y, 880, h, {
    size: 42,
    color: dark ? C.paper : C.ink,
    bold: true,
    fill: dark ? C.ink : C.paper,
  });
}

export function note(slide, body, dark = false) {
  text(slide, body, 56, 676, 780, 24, {
    size: 10,
    color: dark ? "#B7C6CE" : C.muted,
    fill: dark ? C.ink : C.paper,
  });
}

export function page(slide, n, dark = false) {
  text(slide, String(n).padStart(2, "0"), 1190, 674, 34, 24, {
    size: 12,
    color: dark ? "#B7C6CE" : C.muted,
    align: "right",
    fill: dark ? C.ink : C.paper,
  });
}

export function line(slide, x, y, w, color = C.line, h = 2) {
  rect(slide, x, y, w, h, color, color, 0);
}

export function metric(slide, value, label, x, y, w, color) {
  rect(slide, x, y, w, 96, color, color, 0);
  text(slide, value, x + 18, y + 15, w - 36, 38, { size: 33, color: C.white, bold: true, fill: color });
  text(slide, label, x + 18, y + 57, w - 36, 28, { size: 13, color: C.white, fill: color });
}

export function pill(slide, body, x, y, w, color) {
  const p = rect(slide, x, y, w, 34, color, color, 0, true);
  text(slide, body, x + 12, y + 7, w - 24, 18, { size: 12, color: C.white, bold: true, align: "center", fill: color });
  return p;
}

export function flowNode(slide, label, x, y, w, h, fill, border = C.line) {
  rect(slide, x, y, w, h, fill, border, 1, true);
  text(slide, label, x + 14, y + 14, w - 28, h - 24, { size: 17, color: C.ink, bold: true, align: "center", valign: "middle", fill });
}

export function connector(slide, x1, y1, x2, y2, color = C.muted) {
  if (Math.abs(y2 - y1) < 4) {
    line(slide, x1, y1, x2 - x1, color, 3);
    rect(slide, x2 - 8, y1 - 5, 10, 10, color, color, 0);
    return;
  }
  const midX = (x1 + x2) / 2;
  line(slide, x1, y1, midX - x1, color, 3);
  rect(slide, midX, Math.min(y1, y2), 3, Math.abs(y2 - y1), color, color, 0);
  line(slide, midX, y2, x2 - midX, color, 3);
  rect(slide, x2 - 8, y2 - 5, 10, 10, color, color, 0);
}

