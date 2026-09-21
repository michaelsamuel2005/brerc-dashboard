#!/usr/bin/env node

import { access, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const webRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const entryPoint = join(
  webRoot,
  "node_modules",
  "maplibre-gl",
  "dist",
  "maplibre-gl-worker.mjs",
);
const outputFile = join(webRoot, "public", "maplibre-gl-worker.cjs");

try {
  await access(entryPoint);
} catch {
  throw new Error(
    "MapLibre worker source is missing; run npm ci before building the map worker.",
  );
}

await mkdir(dirname(outputFile), { recursive: true });
await build({
  entryPoints: [entryPoint],
  outfile: outputFile,
  bundle: true,
  format: "iife",
  platform: "browser",
  target: ["es2022"],
  minify: true,
  legalComments: "eof",
  logLevel: "info",
});
