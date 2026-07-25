#!/usr/bin/env node
// C2 guard: a fast, coarse net that fails if any forbidden client field name or obvious
// secret appears in the SOURCE (comments stripped, test files excluded). It runs in CI
// alongside the Zod .strict() contract test, which is the precise, runtime gate.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = "src";
// Distinctive server-only field names that must never reach client code/data.
const FORBIDDEN = [/\bRecorder1\b/i, /\bBLISS\b/i, /\bEastings\b/i, /\bNorthings\b/i];
const SECRET = [
  /\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{10,}/,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /\bAKIA[0-9A-Z]{16}\b/,
];
const PATTERNS = [...FORBIDDEN, ...SECRET];

const hits = [];
function stripComments(lines) {
  let inBlock = false;
  return lines.map((raw) => {
    let line = raw;
    if (inBlock) {
      const end = line.indexOf("*/");
      if (end === -1) return "";
      line = line.slice(end + 2);
      inBlock = false;
    }
    line = line.replace(/\/\*.*?\*\//g, "");
    const open = line.indexOf("/*");
    if (open !== -1) {
      inBlock = true;
      line = line.slice(0, open);
    }
    return line.replace(/\/\/.*$/, "");
  });
}
function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      walk(p);
      continue;
    }
    if (/\.test\.[tj]sx?$/.test(name)) continue; // tests intentionally exercise hostile data
    if (!/\.(ts|tsx|js|jsx|mjs|css|html|json)$/.test(name)) continue;
    const code = stripComments(readFileSync(p, "utf8").split(/\r?\n/));
    code.forEach((line, i) => {
      if (!line.trim()) return;
      for (const re of PATTERNS) if (re.test(line)) hits.push(`${p}:${i + 1}  ${line.trim().slice(0, 90)}`);
    });
  }
}
walk(ROOT);
if (hits.length) {
  console.error(`C2 guard FAILED — ${hits.length} forbidden pattern(s) in source:`);
  for (const h of hits) console.error("  " + h);
  process.exit(1);
}
console.log("C2 guard passed — no forbidden field names or secrets in src/.");
