// scripts/demo-capture.mjs
// Reproducible capture for assets/demo-cli.gif.
//
// Loads design-preview/demo-storyboard.html, screenshots each <section.frame>
// at an identical 1280px viewport (headless), and writes PNGs to
// $TMPDIR/demo-frames/. Then ffmpeg (two-pass palette) assembles the GIF.
//
// The capture is deterministic — no cursor, no OS chrome, no running app —
// so the GIF can be regenerated whenever the UI changes instead of going stale.
//
// Usage:
//   node scripts/demo-capture.mjs            # capture frames only
//   node scripts/demo-capture.mjs --gif      # capture + assemble the GIF
//
// Requires the `playwright` npm package and a one-time `npx playwright install
// chromium`. If Playwright is not installed, fall back to the integrated browser
// tools (screenshot_page) over the same HTML file — but keep this script
// committed so the capture stays regenerable.
import { chromium } from "playwright";
import { mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const HTML = path.join(ROOT, "design-preview", "demo-storyboard.html");
const OUT = path.join(process.env.TMPDIR || "/tmp", "demo-frames");
const WANT_GIF = process.argv.includes("--gif");
const GIF_OUT = path.join(ROOT, "assets", "demo-cli.gif");

const VIEWPORT = { width: 1280, height: 800, deviceScaleFactor: 2 };

async function main() {
  if (!existsSync(HTML)) throw new Error(`missing ${HTML}`);
  await rm(OUT, { recursive: true, force: true });
  await mkdir(OUT, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: 2 });
  await page.goto("file://" + HTML, { waitUntil: "networkidle" });

  const ids = await page.$$eval("section.frame", (els) => els.map((e) => e.id));
  if (!ids.length) throw new Error("no .frame sections found");

  for (let i = 0; i < ids.length; i++) {
    const id = ids[i];
    const el = await page.$(`#${id}`);
    // Each frame is a fixed 1280px card; screenshot the element itself so the
    // capture is identical across runs regardless of body padding.
    await el.screenshot({
      path: path.join(OUT, `frame-${String(i).padStart(2, "0")}.png`),
      type: "png",
    });
    console.log(`captured ${id} -> frame-${String(i).padStart(2, "0")}.png`);
  }

  await browser.close();

  if (WANT_GIF) {
    const { execFileSync } = await import("node:child_process");
    const palette = path.join(OUT, "palette.png");
    const vf =
      "fps=10,scale=820:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse";
    // two-pass: generate palette, then map frames onto it
    execFileSync("ffmpeg", [
      "-y", "-i", path.join(OUT, "frame-%02d.png"),
      "-vf", "palettegen=max_colors=256", palette,
    ]);
    execFileSync("ffmpeg", [
      "-y", "-framerate", "10", "-i", path.join(OUT, "frame-%02d.png"),
      "-i", palette,
      "-filter_complex", "scale=820:-1:flags=lanczos[x];[x][1:v]paletteuse",
      "-loop", "0", GIF_OUT,
    ]);
    console.log(`gif -> ${GIF_OUT}`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});