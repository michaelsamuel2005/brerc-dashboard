import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Reads the real stylesheet rather than a copy of its values, so a token can never be
// changed in CSS while a passing test quietly asserts the old colour. Vitest runs with
// the Vite root (web/) as cwd; the length assertion below turns a wrong path into an
// obvious failure instead of an empty parse that silently checks nothing.
const CSS = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");
if (CSS.length < 2000) throw new Error(`tokens.css looks truncated (${CSS.length} bytes)`);

type Tokens = Record<string, string>;

/** Pull the custom properties out of the first rule whose selector matches. */
function block(selector: string): string {
  const start = CSS.indexOf(selector);
  expect(start, `selector not found in tokens.css: ${selector}`).toBeGreaterThan(-1);
  const open = CSS.indexOf("{", start);
  const close = CSS.indexOf("}", open);
  return CSS.slice(open + 1, close);
}

function parse(source: string): Tokens {
  const tokens: Tokens = {};
  for (const match of source.matchAll(/--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;/g)) {
    const [, name, value] = match;
    if (name && value) tokens[name] = value;
  }
  return tokens;
}

/** WCAG 2.x relative luminance. */
function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
  const channel = (offset: number) => {
    const v = parseInt(full.slice(offset, offset + 2), 16) / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

const LIGHT = parse(block(":root {"));
const DARK = parse(block(':root[data-theme="dark"] {'));

interface Pair {
  fg: string;
  bg: string;
  min: number;
  what: string;
}

// 4.5:1 — WCAG 1.4.3 Contrast (Minimum), body-size text.
const TEXT: Pair[] = [
  { fg: "body", bg: "paper", min: 4.5, what: "body text on the page" },
  { fg: "body", bg: "panel", min: 4.5, what: "body text in a card" },
  { fg: "body", bg: "panel-2", min: 4.5, what: "body text on a tinted panel" },
  { fg: "ink", bg: "paper", min: 4.5, what: "headings on the page" },
  { fg: "ink", bg: "panel", min: 4.5, what: "headings in a card" },
  { fg: "ink", bg: "panel-2", min: 4.5, what: "headings on a tinted panel" },
  { fg: "muted", bg: "paper", min: 4.5, what: "secondary text on the page" },
  { fg: "muted", bg: "panel", min: 4.5, what: "secondary text in a card" },
  { fg: "muted", bg: "panel-2", min: 4.5, what: "secondary text on a tinted panel" },
  { fg: "green-d", bg: "paper", min: 4.5, what: "links on the page" },
  { fg: "green-d", bg: "panel", min: 4.5, what: "links in a card" },
  { fg: "green-dd", bg: "paper-2", min: 4.5, what: "the current navigation item" },
  { fg: "accent-d", bg: "paper", min: 4.5, what: "eyebrow text on the page" },
  { fg: "accent-d", bg: "panel", min: 4.5, what: "accent text in a card" },
  { fg: "accent-d", bg: "accent-bg", min: 4.5, what: "accent text on its own tint" },
  { fg: "danger", bg: "paper", min: 4.5, what: "error text on the page" },
  { fg: "danger", bg: "panel", min: 4.5, what: "error text in a card" },
  { fg: "btn-fg", bg: "btn-bg", min: 4.5, what: "a button label" },
  // The hero is a gradient, so every pair is measured against --hero-b, the LIGHTER
  // end: text that clears it clears the whole panel. This is the check that was
  // missing when the hero painted white on --green-dd, which is a pale mint in dark
  // mode and left the lead paragraph and the search button unreadable.
  { fg: "hero-fg", bg: "hero-b", min: 4.5, what: "hero heading text" },
  { fg: "hero-fg-muted", bg: "hero-b", min: 4.5, what: "hero body text" },
  { fg: "hero-fg", bg: "hero-a", min: 4.5, what: "hero heading at the dark end" },
  { fg: "hero-fg-muted", bg: "hero-a", min: 4.5, what: "hero body at the dark end" },
  { fg: "hero-btn-fg", bg: "hero-btn-bg", min: 4.5, what: "the hero search button label" },
];

// 3:1 — WCAG 1.4.11 Non-text Contrast. Only things the success criterion actually
// covers: the boundary of an input (you cannot find the field without it), the focus
// ring, a button's edge against the page, and chart bars, which ARE the data.
//
// `--line` is deliberately NOT here. It draws decorative card edges and table rules,
// and 1.4.11 exempts decoration: the card is identifiable from its background, shadow
// and heading, and no state is conveyed by that border. Asserting 3:1 on it would
// force heavy grey boxes for no accessibility gain — a real cost for a fake win.
const NON_TEXT: Pair[] = [
  { fg: "control-line", bg: "panel", min: 3, what: "the border of a text input" },
  { fg: "control-line", bg: "paper", min: 3, what: "an input border on the page" },
  { fg: "control-line", bg: "panel-2", min: 3, what: "an input border on a tinted panel" },
  { fg: "focus", bg: "paper", min: 3, what: "the focus ring on the page" },
  { fg: "focus", bg: "panel", min: 3, what: "the focus ring in a card" },
  { fg: "btn-bg", bg: "paper", min: 3, what: "a button against the page" },
  { fg: "chart", bg: "panel", min: 3, what: "chart bars against the card" },
  { fg: "chart-2", bg: "panel", min: 3, what: "the second chart series" },
  { fg: "hero-btn-bg", bg: "hero-b", min: 3, what: "the hero search button against the hero" },
];

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
])("%s theme", (theme, tokens) => {
  it("defines every token the pairs below reference", () => {
    const referenced = new Set([...TEXT, ...NON_TEXT].flatMap((p) => [p.fg, p.bg]));
    for (const name of referenced) {
      expect(tokens[name], `--${name} is missing from the ${theme} theme`).toMatch(/^#[0-9a-fA-F]+$/);
    }
  });

  it.each(TEXT)("$what reaches $min:1 (WCAG 1.4.3)", ({ fg, bg, min }) => {
    const ratio = contrast(tokens[fg]!, tokens[bg]!);
    expect(
      Number(ratio.toFixed(2)),
      `--${fg} (${tokens[fg]}) on --${bg} (${tokens[bg]}) is ${ratio.toFixed(2)}:1`,
    ).toBeGreaterThanOrEqual(min);
  });

  it.each(NON_TEXT)("$what reaches $min:1 (WCAG 1.4.11)", ({ fg, bg, min }) => {
    const ratio = contrast(tokens[fg]!, tokens[bg]!);
    expect(
      Number(ratio.toFixed(2)),
      `--${fg} (${tokens[fg]}) on --${bg} (${tokens[bg]}) is ${ratio.toFixed(2)}:1`,
    ).toBeGreaterThanOrEqual(min);
  });
});

describe("the two dark-theme declarations", () => {
  // One block serves an explicit choice on /settings, the other serves a system
  // preference. They must not drift: a visitor who never opened /settings would
  // otherwise get different, unmeasured colours from one who did.
  it("declare exactly the same tokens with exactly the same values", () => {
    const systemPreference = parse(block(':root:not([data-theme="light"]) {'));
    expect(systemPreference).toEqual(DARK);
    expect(Object.keys(systemPreference).length).toBeGreaterThan(10);
  });
});

describe("the measurement itself", () => {
  // A contrast test that cannot fail is worse than no test: it reports safety it has
  // not checked. These anchor the maths to values with known answers.
  it("computes the reference ratios", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    // #767676 on white is the canonical 4.5:1 boundary used in WCAG examples.
    expect(contrast("#767676", "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#777777", "#ffffff")).toBeLessThan(4.5);
  });

  it("is order-independent and handles shorthand hex", () => {
    expect(contrast("#000", "#fff")).toBeCloseTo(contrast("#fff", "#000"), 10);
    expect(contrast("#fff", "#ffffff")).toBeCloseTo(1, 10);
  });
});
