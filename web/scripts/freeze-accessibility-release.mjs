#!/usr/bin/env node

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const webRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repositoryRoot = dirname(webRoot);

const HELP = `Freeze the exact accessibility review target.

Run npm run build and npm run guard:bundle first, then supply:

  A11Y_EXPECTED_SHA                 exact 40-character commit SHA
  A11Y_REPOSITORY_ID                public identifier, e.g. github.com/org/repo
  A11Y_DEPLOYED_URL                 final HTTPS review URL
  A11Y_CI_RUN_URL                   CI run for that exact SHA
  A11Y_HOSTING_ARRANGEMENT          e.g. BRERC subdomain, same-origin API
  A11Y_PUBLIC_DATA_RELEASE_ID       deployed publication release ID
  A11Y_BUILD_ARTIFACT_DIR           unpacked exact CI artifact that was deployed
  A11Y_RUNTIME_CONFIG_FILE          reviewed runtime configuration
  A11Y_MEDIA_MANIFEST_FILE          approved media manifest
  A11Y_TILE_PRIVACY_CONFIG_FILE     approved tile/privacy configuration

Optional:

  A11Y_OUTPUT_FILE                  defaults to
                                    test-results/a11y-release-target.json

The output contains hashes and identifiers, never the contents of the three
configuration inputs. The command refuses a dirty tree or an SHA mismatch.
`;

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log(HELP);
  process.exit(0);
}

function fail(message) {
  console.error(`accessibility release freeze FAILED — ${message}`);
  process.exit(1);
}

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) fail(`${name} is required`);
  return value;
}

function git(args) {
  return execFileSync("git", args, {
    cwd: repositoryRoot,
    encoding: "utf8",
  }).trim();
}

function sha256Bytes(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function sha256File(path) {
  let stat;
  try {
    stat = statSync(path);
  } catch {
    fail(`required evidence input does not exist: ${path}`);
  }
  if (!stat.isFile()) fail(`required evidence input is not a file: ${path}`);
  return `sha256:${sha256Bytes(readFileSync(path))}`;
}

function resolveInput(value) {
  return isAbsolute(value) ? value : join(repositoryRoot, value);
}

function walkFiles(root, current = root) {
  const output = [];
  for (const name of readdirSync(current).sort()) {
    const path = join(current, name);
    const stat = statSync(path);
    if (stat.isDirectory()) output.push(...walkFiles(root, path));
    else if (stat.isFile()) output.push(path);
  }
  return output;
}

function directoryDigest(root) {
  let files;
  try {
    files = walkFiles(root);
  } catch {
    fail(`${relative(repositoryRoot, root)} is missing; run npm run build first`);
  }
  if (files.length === 0) fail(`${relative(repositoryRoot, root)} contains no files`);

  const digest = createHash("sha256");
  for (const path of files) {
    const name = relative(root, path).split("\\").join("/");
    digest.update(name);
    digest.update("\0");
    digest.update(readFileSync(path));
    digest.update("\0");
  }
  return {
    sha256: `sha256:${digest.digest("hex")}`,
    fileCount: files.length,
  };
}

function verifyProductionArtifact(root) {
  const requiredFiles = ["index.html", "maplibre-gl-worker.cjs"];
  for (const name of requiredFiles) {
    const path = join(root, name);
    let stat;
    try {
      stat = statSync(path);
    } catch {
      fail(`production artifact is missing ${name}`);
    }
    if (!stat.isFile() || stat.size === 0) {
      fail(`production artifact has an empty or invalid ${name}`);
    }
  }

  const forbidden = [
    /mockServiceWorker\.js/,
    /msw\/browser/,
    /setupWorker/,
    /\[MSW\]/,
  ];
  const inspectable = walkFiles(root).filter((path) =>
    /\.(?:js|mjs|cjs|css|html)$/.test(path) &&
    !path.endsWith("mockServiceWorker.js")
  );
  for (const path of inspectable) {
    const text = readFileSync(path, "utf8");
    if (forbidden.some((pattern) => pattern.test(text))) {
      fail(`production artifact contains the browser mock layer: ${relative(root, path)}`);
    }
  }
}

function requireHttps(name, value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    fail(`${name} must be a valid absolute URL`);
  }
  if (url.protocol !== "https:") fail(`${name} must use HTTPS`);
  if (url.username || url.password) {
    fail(`${name} must not contain embedded credentials`);
  }
  if (url.hash) fail(`${name} must not contain a URL fragment`);
  return url.toString();
}

const status = git(["status", "--porcelain", "--untracked-files=all"]);
if (status) fail("the repository is not clean; freeze a committed build only");

const expectedSha = required("A11Y_EXPECTED_SHA").toLowerCase();
if (!/^[0-9a-f]{40}$/.test(expectedSha)) {
  fail("A11Y_EXPECTED_SHA must be a full 40-character hexadecimal SHA");
}
const commitSha = git(["rev-parse", "HEAD"]).toLowerCase();
if (commitSha !== expectedSha) {
  fail(`HEAD ${commitSha} does not match A11Y_EXPECTED_SHA ${expectedSha}`);
}

const runtimeConfig = resolveInput(required("A11Y_RUNTIME_CONFIG_FILE"));
const mediaManifest = resolveInput(required("A11Y_MEDIA_MANIFEST_FILE"));
const tilePrivacyConfig = resolveInput(required("A11Y_TILE_PRIVACY_CONFIG_FILE"));
const buildArtifact = resolveInput(required("A11Y_BUILD_ARTIFACT_DIR"));
verifyProductionArtifact(buildArtifact);
const build = directoryDigest(buildArtifact);
const repositoryId = required("A11Y_REPOSITORY_ID");
if (!/^[a-zA-Z0-9.-]+\/[a-zA-Z0-9._/-]+$/.test(repositoryId)) {
  fail("A11Y_REPOSITORY_ID must be a public host/path identifier without credentials");
}

const manifest = {
  schemaVersion: 1,
  generatedAtUtc: new Date().toISOString(),
  repository: repositoryId,
  branch: git(["rev-parse", "--abbrev-ref", "HEAD"]),
  commitSha,
  treeClean: true,
  deployedUrl: requireHttps("A11Y_DEPLOYED_URL", required("A11Y_DEPLOYED_URL")),
  ciRunUrl: requireHttps("A11Y_CI_RUN_URL", required("A11Y_CI_RUN_URL")),
  hostingArrangement: required("A11Y_HOSTING_ARRANGEMENT"),
  publicDataReleaseId: required("A11Y_PUBLIC_DATA_RELEASE_ID"),
  buildArtifact: build,
  packageLockSha256: sha256File(join(webRoot, "package-lock.json")),
  runtimeConfigSha256: sha256File(runtimeConfig),
  approvedMediaManifestSha256: sha256File(mediaManifest),
  tilePrivacyConfigSha256: sha256File(tilePrivacyConfig),
};

const outputValue =
  process.env.A11Y_OUTPUT_FILE?.trim() ||
  join("web", "test-results", "a11y-release-target.json");
const output = isAbsolute(outputValue)
  ? outputValue
  : join(repositoryRoot, outputValue);
mkdirSync(dirname(output), { recursive: true });
try {
  writeFileSync(output, `${JSON.stringify(manifest, null, 2)}\n`, {
    encoding: "utf8",
    flag: "wx",
  });
} catch (error) {
  if (error && typeof error === "object" && error.code === "EEXIST") {
    fail(`output already exists and will not be overwritten: ${output}`);
  }
  throw error;
}
const manifestSha256 = sha256File(output);

console.log(`accessibility release target frozen: ${output}`);
console.log(`manifest: ${manifestSha256}`);
console.log(`commit: ${commitSha}`);
console.log(`build: ${build.sha256} (${build.fileCount} files)`);
