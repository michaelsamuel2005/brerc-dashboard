#!/usr/bin/env node
// Build-output guard: fails if the production bundle contains the MSW mock layer.
//
// Why this exists. `src/main.tsx` starts the mock behind a literal
// `import.meta.env.DEV` test. Vite folds that to `false` when building for
// production, the branch becomes unreachable, and Rollup removes the dynamic
// `import("./test/msw/browser")` along with the whole of MSW — about 300 kB
// (100 kB gzipped) that the public never downloads.
//
// That elimination is silent and fragile. Wrapping the same condition in a
// function call, or moving the import above the guard, keeps the app working
// in dev and in tests while quietly shipping a fake data layer to a public
// dashboard for real BRERC data. This guard turns that from an invisible
// regression into a failed build.
//
// Run it after `npm run build`; it reads dist/ only.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";

const DIST = "dist";

// Strings that only appear if MSW (or its service-worker registration) was
// bundled. Kept narrow and specific so ordinary application code cannot trip it.
const FORBIDDEN = [
  { pattern: /mockServiceWorker\.js/, why: "MSW service-worker registration" },
  { pattern: /msw\/browser/, why: "MSW browser entry point" },
  { pattern: /setupWorker/, why: "MSW worker factory" },
  { pattern: /\[MSW\]/, why: "MSW runtime logging" },
];

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      out.push(...walk(path));
    } else if (/\.(js|mjs|css|html)$/.test(name)) {
      out.push(path);
    }
  }
  return out;
}

let files;
try {
  files = walk(DIST);
} catch {
  console.error(`bundle guard: ${DIST}/ not found — run \`npm run build\` first.`);
  process.exit(1);
}

// public/mockServiceWorker.js is copied into dist/ by Vite because it is a static
// asset MSW needs in dev. It is inert unless a bundle registers it, and the
// checks below are what prove nothing does. Exclude the file itself, not the
// references to it.
const bundles = files.filter((path) => !path.endsWith("mockServiceWorker.js"));

const hits = [];
for (const path of bundles) {
  const text = readFileSync(path, "utf8");
  for (const { pattern, why } of FORBIDDEN) {
    if (pattern.test(text)) hits.push(`${path}: ${why} (${pattern})`);
  }
}

if (hits.length > 0) {
  console.error("bundle guard FAILED — the mock layer is in the production build:");
  for (const hit of hits) console.error(`  ${hit}`);
  console.error(
    "\nCheck that src/main.tsx still returns on a literal `import.meta.env.DEV`\n" +
      "test before anything imports MSW. See the comment in that file.",
  );
  process.exit(1);
}

console.log(`bundle guard passed — no mock layer in ${bundles.length} built files.`);
