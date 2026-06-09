from pathlib import Path
from PIL import Image, ImageDraw
import math


base = Path("/Users/gim-yongjin/Developer/Project/DocuMind/outputs/manual-20260520-rag-table-scope-viz/presentations/rag-table-scope-visuals/template-inspect/source-slides")
paths = sorted(base.glob("source-slide-*.png"))
thumb_w = 360
gap = 24
label_h = 30
cols = 2
thumbs = []
thumb_h = None

for path in paths:
    image = Image.open(path).convert("RGB")
    height = int(image.height * thumb_w / image.width)
    thumb_h = height if thumb_h is None else thumb_h
    thumbs.append((path, image.resize((thumb_w, height))))

rows = math.ceil(len(thumbs) / cols)
out = Image.new("RGB", (cols * thumb_w + (cols + 1) * gap, rows * (thumb_h + label_h) + (rows + 1) * gap), "white")
draw = ImageDraw.Draw(out)

for idx, (path, image) in enumerate(thumbs):
    x = gap + (idx % cols) * (thumb_w + gap)
    y = gap + (idx // cols) * (thumb_h + label_h + gap)
    draw.text((x, y), path.stem.replace("source-slide-", "Slide "), fill=(30, 30, 30))
    out.paste(image, (x, y + label_h))

out.save(base.parent / "source-contact-sheet.png")
