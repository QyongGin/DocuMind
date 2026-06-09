#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  ensureArtifactToolWorkspace,
  importArtifactTool,
  saveBlobToFile,
} from "/Users/gim-yongjin/.codex/plugins/cache/openai-primary-runtime/presentations/26.521.10419/skills/presentations/scripts/artifact_tool_utils.mjs";

const workspace = "/Users/gim-yongjin/Developer/Project/DocuMind/outputs/manual-20260527-rag-ppt/presentations/issue73-rag-ppt";
const pptxPath = "/Users/gim-yongjin/Developer/Project/DocuMind/Assets/발표 PPT/DocuMind_3주차_RAG구조분리_발표본.pptx";
const previewDir = path.join(workspace, "final-preview");
const layoutDir = path.join(workspace, "final-layout");

function slidesFromPresentation(presentation) {
  if (Array.isArray(presentation.slides?.items)) return presentation.slides.items;
  if (Number.isInteger(presentation.slides?.count) && typeof presentation.slides.getItem === "function") {
    return Array.from({ length: presentation.slides.count }, (_, index) => presentation.slides.getItem(index));
  }
  throw new Error("Could not enumerate imported presentation slides.");
}

async function main() {
  await ensureArtifactToolWorkspace(workspace);
  const { FileBlob, PresentationFile } = await importArtifactTool(workspace);
  const presentation = await PresentationFile.importPptx(await FileBlob.load(pptxPath));
  const slides = slidesFromPresentation(presentation);
  await fs.mkdir(previewDir, { recursive: true });
  await fs.mkdir(layoutDir, { recursive: true });

  for (const slideNumber of [5, 6]) {
    const slide = slides[slideNumber - 1];
    const png = await presentation.export({ slide, format: "png", scale: 1 });
    await saveBlobToFile(png, path.join(previewDir, `slide-${String(slideNumber).padStart(2, "0")}.png`));
    const layout = await presentation.export({ slide, format: "layout" });
    await saveBlobToFile(layout, path.join(layoutDir, `slide-${String(slideNumber).padStart(2, "0")}.layout.json`));
  }

  console.log(
    JSON.stringify(
      {
        pptxPath,
        slideCount: slides.length,
        previewDir,
        layoutDir,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
