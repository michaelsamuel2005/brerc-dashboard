import { beforeEach, describe, expect, it } from "vitest";
import {
  applyDensity,
  applyTheme,
  densityAttribute,
  nextTheme,
  readDensity,
  readTheme,
  themeAttribute,
} from "./theme";

describe("readTheme", () => {
  it("accepts the three supported values", () => {
    expect(readTheme("system")).toBe("system");
    expect(readTheme("light")).toBe("light");
    expect(readTheme("dark")).toBe("dark");
  });

  it("falls back to system for anything else, including tampered storage", () => {
    for (const raw of [null, "", "DARK", "blue", "0", "{}", "<script>"]) {
      expect(readTheme(raw)).toBe("system");
    }
  });
});

describe("readDensity", () => {
  it("accepts the supported values and defaults to comfortable", () => {
    expect(readDensity("compact")).toBe("compact");
    expect(readDensity("comfortable")).toBe("comfortable");
    for (const raw of [null, "", "COMPACT", "tiny"]) {
      expect(readDensity(raw)).toBe("comfortable");
    }
  });
});

describe("themeAttribute", () => {
  it("removes the attribute for system, so the OS preference still governs", () => {
    // The important case: a visitor who never chose must not be forced to light.
    expect(themeAttribute("system")).toBeNull();
  });

  it("names the theme for an explicit choice", () => {
    expect(themeAttribute("light")).toBe("light");
    expect(themeAttribute("dark")).toBe("dark");
  });
});

describe("densityAttribute", () => {
  it("carries no attribute for the default", () => {
    expect(densityAttribute("comfortable")).toBeNull();
    expect(densityAttribute("compact")).toBe("compact");
  });
});

describe("nextTheme", () => {
  it("moves away from whatever is currently on screen", () => {
    expect(nextTheme("system", true)).toBe("light");
    expect(nextTheme("system", false)).toBe("dark");
    expect(nextTheme("dark", false)).toBe("light");
    expect(nextTheme("light", false)).toBe("dark");
    // An explicit choice ignores the system preference — the visitor already decided.
    expect(nextTheme("dark", true)).toBe("light");
    expect(nextTheme("light", true)).toBe("dark");
  });

  it("always changes the visible appearance", () => {
    for (const current of ["system", "light", "dark"] as const) {
      for (const systemDark of [true, false]) {
        const visibleNow = current === "system" ? (systemDark ? "dark" : "light") : current;
        expect(nextTheme(current, systemDark)).not.toBe(visibleNow);
      }
    }
  });
});

describe("applying preferences to an element", () => {
  let root: HTMLElement;

  beforeEach(() => {
    root = document.createElement("html");
  });

  it("sets and clears data-theme", () => {
    applyTheme("dark", root);
    expect(root.getAttribute("data-theme")).toBe("dark");
    applyTheme("light", root);
    expect(root.getAttribute("data-theme")).toBe("light");
    applyTheme("system", root);
    expect(root.hasAttribute("data-theme")).toBe(false);
  });

  it("sets and clears data-density", () => {
    applyDensity("compact", root);
    expect(root.getAttribute("data-density")).toBe("compact");
    applyDensity("comfortable", root);
    expect(root.hasAttribute("data-density")).toBe(false);
  });
});
