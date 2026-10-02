#!/usr/bin/env node
// Capture screenshots + console errors of the running dev app for review.
//   1) in one terminal:  npm run dev
//   2) in another:       node scripts/screenshots.mjs
// Output: web/screenshots/*.png and web/screenshots/report.txt (both git-ignored).
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

// NB: do not name a variable `URL` — it shadows the global URL constructor.
const APP_URL = process.env.APP_URL ?? "http://localhost:5173/";
const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "screenshots") + path.sep;
fs.mkdirSync(OUT, { recursive: true });

const log = [];
function watch(page, label) {
  page.on("console", (m) => { if (m.type() === "error") log.push(`[${label}] CONSOLE ${m.text().slice(0, 200)}`); });
  page.on("pageerror", (e) => log.push(`[${label}] PAGEERROR ${String(e).slice(0, 200)}`));
  page.on("requestfailed", (r) => log.push(`[${label}] REQFAIL ${r.url().slice(0, 110)} ${r.failure()?.errorText ?? ""}`));
}

// Start the dev server ourselves if it isn't already running, so this is one command.
async function reachable(url) {
  try {
    await fetch(url, { signal: AbortSignal.timeout(1500) });
    return true;
  } catch {
    return false;
  }
}
let devServer = null;
if (!(await reachable(APP_URL))) {
  console.log("Dev server not running — starting it…");
  devServer = spawn("npm", ["run", "dev"], { cwd: path.join(path.dirname(fileURLToPath(import.meta.url)), ".."), stdio: "ignore", detached: false });
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline && !(await reachable(APP_URL))) await new Promise((r) => setTimeout(r, 700));
  if (!(await reachable(APP_URL))) {
    devServer.kill();
    throw new Error(`Could not start the dev server at ${APP_URL}. Run "npm run dev" manually and retry.`);
  }
  console.log("Dev server ready.");
}

const browser = await chromium.launch();
try {
  // ---------- desktop ----------
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await desktop.newPage();
  watch(page, "desktop");
  await page.goto(APP_URL, { waitUntil: "load", timeout: 30000 });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(3000); // let the map tiles + chart paint
  await page.screenshot({ path: OUT + "01-desktop-full.png", fullPage: true });

  // a grid square selected (map highlight + card + row)
  const cellBtn = page.getByRole("button", { name: /^ST\d/ }).first();
  if (await cellBtn.count()) {
    await cellBtn.click();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: OUT + "02-desktop-cell-selected.png", fullPage: true });
  }

  // a year selected (cross-filter)
  const summary = page.locator(".chart-table > summary");
  if (await summary.count()) {
    await summary.scrollIntoViewIfNeeded();
    await summary.click();
    const yearBtn = page.locator(".chart-table").getByRole("button", { name: /2024/ }).first();
    if (await yearBtn.count()) {
      await yearBtn.click();
      await page.waitForTimeout(1500);
      await page.screenshot({ path: OUT + "03-desktop-year-2024.png", fullPage: true });
    }
  }
  await desktop.close();

  // ---------- mobile ----------
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const mpage = await mobile.newPage();
  watch(mpage, "mobile");
  await mpage.goto(APP_URL, { waitUntil: "load", timeout: 30000 });
  await mpage.waitForLoadState("networkidle").catch(() => {});
  await mpage.waitForTimeout(3000);
  await mpage.screenshot({ path: OUT + "04-mobile-full.png", fullPage: true });
  await mobile.close();
} finally {
  await browser.close();
  if (devServer) devServer.kill();
}

const report = (log.length ? [...new Set(log)] : ["No console errors, page errors or failed requests."]).join("\n");
fs.writeFileSync(OUT + "report.txt", report + "\n");
console.log(report);
console.log("\nScreenshots written to web/screenshots/");
