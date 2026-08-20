// scripts/capture-real-ui.mjs
// Captures the real Prompt Playoff UI and assembles TWO demo GIFs:
//   1. assets/demo-cli.gif  — hero flow: DESCRIBE → RECOMMEND → COMPILE → BENCHMARK
//   2. assets/demo-ui.gif   — UI tour: all sections with fade transitions
//
// Both include on-screen text annotations for clarity.
//
// Usage:
//   node scripts/capture-real-ui.mjs              # capture frames only
//   node scripts/capture-real-ui.mjs --gif        # capture + assemble GIFs
//   node scripts/capture-real-ui.mjs --hero       # hero GIF only
//   node scripts/capture-real-ui.mjs --tour       # UI tour GIF only
//
// Requires: `playwright-core` (uses system Google Chrome) + running server.
import { chromium } from "playwright-core";
import { mkdir, rm } from "node:fs/promises";
import { unlinkSync, readdirSync, copyFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const OUT = path.join(process.env.TMPDIR || "/tmp", "pp-demo-frames");
const WANT_HERO = process.argv.includes("--hero");
const WANT_TOUR = process.argv.includes("--tour");
const WANT_GIF = process.argv.includes("--gif") || WANT_HERO || WANT_TOUR;
const DO_HERO = !WANT_TOUR;  // default: both
const DO_TOUR = !WANT_HERO;  // default: both
const HERO_OUT = path.join(ROOT, "assets", "demo-cli.gif");
const TOUR_OUT = path.join(ROOT, "assets", "demo-ui.gif");
const BASE = process.env.PP_URL || "http://localhost:8000";

const VIEWPORT = { width: 1280, height: 800, deviceScaleFactor: 2 };
const TASK =
  "Extract named entities from text into strict JSON with fields: person, place, organization. Never invent values.";

// ── GIF assembly helper ──
function buildGif(framesDir, gifOut, fps = 5, colors = 256) {
  const seqGlob = path.join(framesDir, "frame-%05d.png");
  const palette = path.join(framesDir, "palette.png");
  execFileSync("ffmpeg", ["-y", "-framerate", String(fps), "-i", seqGlob, "-vf", `palettegen=max_colors=${colors}`, palette]);
  execFileSync("ffmpeg", ["-y", "-framerate", String(fps), "-i", seqGlob, "-i", palette,
    "-filter_complex", "scale=820:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3", "-fps_mode", "vfr", "-loop", "0", gifOut]);
  console.log(`gif -> ${gifOut}`);
}

async function main() {
  await rm(OUT, { recursive: true, force: true });
  await mkdir(OUT, { recursive: true });

  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  const page = await browser.newPage({ viewport: VIEWPORT });

  // ── Shared helpers ──
  const hold = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitUntil = async (predicate, { timeout = 60000, msg = "" } = {}) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      try { if (await page.evaluate(predicate)) return true; } catch (_) {}
      await page.waitForTimeout(300);
    }
    console.warn(`timed out: ${msg}`); return false;
  };
  const typeSlow = async (selector, text, delay = 35) => {
    await page.click(selector); await page.fill(selector, "");
    for (const ch of text) await page.type(selector, ch, { delay });
  };

  // ── On-screen annotation overlay ──
  let annotationReady = false;
  const ensureAnnotation = async () => {
    if (annotationReady) return;
    await page.addStyleTag({ content: `
      #pp-anno {
        position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%);
        z-index: 999998; padding: 12px 28px;
        background: rgba(14,16,20,.92); border: 1px solid rgba(227,179,65,.45);
        border-radius: 10px; color: #b8bec9; font: 600 18px/1.3 Inter,system-ui,sans-serif;
        letter-spacing: .02em; pointer-events: none; opacity: 0;
        transition: opacity 400ms ease; backdrop-filter: blur(6px);
        box-shadow: 0 4px 20px rgba(0,0,0,.4); white-space: nowrap;
      }
      #pp-fade {
        position: fixed; inset: 0; z-index: 999999;
        background: #0e1014; opacity: 0; pointer-events: none;
        transition: opacity 600ms ease-in-out;
      }
    ` });
    await page.evaluate(() => {
      document.body.appendChild(Object.assign(document.createElement("div"), { id: "pp-fade" }));
      document.body.appendChild(Object.assign(document.createElement("div"), { id: "pp-anno" }));
    });
    annotationReady = true;
  };
  const showAnnotation = async (text) => {
    await ensureAnnotation();
    await page.evaluate((t) => { const e = document.getElementById("pp-anno"); if (e) { e.textContent = t; e.style.opacity = "1"; } }, text);
  };
  const hideAnnotation = async () => {
    await page.evaluate(() => { const e = document.getElementById("pp-anno"); if (e) e.style.opacity = "0"; });
  };
  const fadeTransition = async (navigateFn) => {
    await ensureAnnotation();
    await page.evaluate(() => { const f = document.getElementById("pp-fade"); if (f) f.style.opacity = "1"; });
    await hold(1000);
    await navigateFn();
    await hold(700);
    await page.evaluate(() => { const f = document.getElementById("pp-fade"); if (f) f.style.opacity = "0"; });
    await hold(1200);
  };

  // ── Frame grabber ──
  let i = 0;
  let capturing = false;
  let framesPrefix = "hero";
  const captureLoop = async () => {
    while (capturing) {
      try { await page.screenshot({ path: path.join(OUT, `${framesPrefix}-${String(i).padStart(5,"0")}.png`), fullPage: false }); i++; } catch (_) {}
      await new Promise((r) => setTimeout(r, 200));
    }
  };
  const startCap = (prefix) => { framesPrefix = prefix; i = 0; capturing = true; captureLoop(); };
  const stopCap = async () => { capturing = false; await hold(400); };

  // ── Common flow: create prompt + benchmark ──
  const runCoreFlow = async () => {
    await page.goto(BASE + "/", { waitUntil: "networkidle" });
    await hold(600);
    startCap("hero");
    await showAnnotation("Prompt Playoff — find the best prompt technique");
    await hold(2000);

    await page.getByRole("button", { name: "Enter the workbench" }).click();
    await showAnnotation("Step 1 — Describe your task");
    await hold(3500);

    await fadeTransition(async () => { await page.goto(BASE + "/#prompt", { waitUntil: "networkidle" }); });
    await hold(1500);
    await typeSlow("#description", TASK, 35);
    await hold(1500);

    await showAnnotation("Step 2 — Create your prompt");
    await page.locator("#select-btn").click();
    console.log("clicked Create my prompt…");
    await waitUntil(
      () => { const r = document.querySelector("#results"); return r && !!r.querySelector(".result, .recommended-result"); },
      { timeout: 60000, msg: "results populated" },
    );
    await showAnnotation("Step 3 — Ranked techniques");
    await hold(3500);

    await page.locator("#detail").scrollIntoViewIfNeeded().catch(() => {});
    await showAnnotation("Step 4 — Compiled prompt");
    await hold(4000);

    // Benchmark
    await fadeTransition(async () => {
      await page.goto(BASE + "/#report", { waitUntil: "networkidle" });
      await page.waitForTimeout(1000);
      const ds = page.locator('[data-run-field="dataset"]').first();
      if (await ds.count()) { await ds.selectOption("entity-extraction"); await page.waitForTimeout(600); }
    });
    await showAnnotation("Step 5 — Benchmark on 6 examples");
    await hold(3000);
    await page.locator("#bench-btn").click();
    console.log("clicked Measure now…");
    await waitUntil(
      () => { const t = document.querySelector("#detail"); if (!t) return false; const x = t.innerText||""; return (x.includes("quality")||x.includes("Quality")||x.includes("score")) && !/measuring|running|loading/i.test(x); },
      { timeout: 120000, msg: "benchmark results" },
    );
    await showAnnotation("Step 6 — Quality results");
    await hold(4000);
    await page.locator("#detail").scrollIntoViewIfNeeded().catch(() => {});
    await hold(2000);

    // Final fade
    await hideAnnotation();
    await page.evaluate(() => { const f = document.getElementById("pp-fade"); if (f) f.style.opacity = "1"; });
    await hold(1200);
  };

  // ── Tour flow: visit all sections ──
  const tourSections = [
    ["#techniques", "Techniques — 61 methods"],
    ["#dataset-library", "Datasets — library"],
    ["#dataset-upload", "Datasets — upload your own"],
    ["#dataset-hub", "Datasets — Hugging Face import"],
    ["#dataset-builder", "Datasets — build your own"],
    ["#dataset-bundled", "Datasets — shipped with the tool"],
    ["#history", "Check — results history"],
    ["#judge", "Check — pairwise judging"],
    ["#model-matrix", "Check — model matrix"],
    ["#context-lab", "Check — context lab"],
    ["#analysis", "Check — significance analysis"],
    ["#regressions", "Production — regressions"],
    ["#reviews", "Production — reviews"],
    ["#releases", "Production — releases"],
    ["#production", "Production — spot checks"],
    ["#settings", "Reference — models & keys"],
    ["#logs", "Reference — jobs & logs"],
    ["#evaluation", "Reference — evaluation guide"],
    ["#help", "Reference — help"],
  ];

  const runTour = async () => {
    startCap("tour");
    for (const [hash, label] of tourSections) {
      await fadeTransition(async () => { await page.goto(BASE + hash, { waitUntil: "networkidle" }); });
      await showAnnotation(label);
      await hold(1800);
    }
    await hideAnnotation();
    await page.evaluate(() => { const f = document.getElementById("pp-fade"); if (f) f.style.opacity = "1"; });
    await hold(1200);
  };

  // ── Execute ──
  if (DO_HERO) {
    console.log("=== HERO GIF ===");
    await runCoreFlow();
    await stopCap();
    // Rename hero frames to sequential pattern for ffmpeg
    const heroFrames = readdirSync(OUT).filter(f => f.startsWith("hero-")).sort();
    heroFrames.forEach((f, idx) => copyFileSync(path.join(OUT, f), path.join(OUT, `frame-${String(idx).padStart(5,"0")}.png`)));
    if (WANT_GIF) buildGif(OUT, HERO_OUT, 5, 256);
    // Clean up hero frames + sequential copies
    readdirSync(OUT).filter(f => f.startsWith("hero-") || f.startsWith("frame-") || f.startsWith("palette")).forEach(f => { try { unlinkSync(path.join(OUT, f)); } catch(_){} });
  }

  if (DO_TOUR) {
    console.log("=== UI TOUR GIF ===");
    // Need to re-run core flow to get into the app state, then tour
    if (!DO_HERO) {
      await page.goto(BASE + "/", { waitUntil: "networkidle" });
      await hold(500);
      await page.getByRole("button", { name: "Enter the workbench" }).click();
      await hold(1500);
      await page.goto(BASE + "/#prompt", { waitUntil: "networkidle" });
      await page.locator("#description").fill(TASK);
      await page.locator("#select-btn").click();
      await waitUntil(() => { const r = document.querySelector("#results"); return r && !!r.querySelector(".result"); }, { timeout: 60000, msg: "results" });
      await hold(2000);
    }
    await runTour();
    await stopCap();
    const tourFrames = readdirSync(OUT).filter(f => f.startsWith("tour-")).sort();
    tourFrames.forEach((f, idx) => copyFileSync(path.join(OUT, f), path.join(OUT, `frame-${String(idx).padStart(5,"0")}.png`)));
    if (WANT_GIF) buildGif(OUT, TOUR_OUT, 4, 128);
  }

  await browser.close();
  console.log("done");
}

main().catch((e) => { console.error(e); process.exit(1); });