import { describe, expect, it } from "vitest";
import { currentNavHref, FOOTER_ITEMS, NAV_ITEMS } from "./navigation";

describe("NAV_ITEMS", () => {
  it("lists the five primary destinations, each exactly once", () => {
    expect(NAV_ITEMS.map((item) => item.href)).toEqual([
      "/",
      "/explore",
      "/species",
      "/records",
      "/about",
    ]);
    const hrefs = new Set(NAV_ITEMS.map((item) => item.href));
    expect(hrefs.size).toBe(NAV_ITEMS.length);
  });

  it("gives every item a non-empty label", () => {
    for (const item of [...NAV_ITEMS, ...FOOTER_ITEMS]) {
      expect(item.label.trim().length).toBeGreaterThan(0);
    }
  });

  it("keeps the statutory pages reachable", () => {
    // Both are legal obligations for a public sector body; losing the link loses the
    // obligation, so this asserts they exist rather than trusting the footer markup.
    expect(FOOTER_ITEMS.map((item) => item.href)).toContain("/accessibility");
    expect(FOOTER_ITEMS.map((item) => item.href)).toContain("/privacy");
  });
});

describe("currentNavHref", () => {
  it("marks the overview only on an exact match", () => {
    // The bug this prevents: "/" prefix-matches everything, so a naive startsWith
    // would announce "Overview, current page" on every page of the site.
    expect(currentNavHref("/")).toBe("/");
    expect(currentNavHref("/species")).not.toBe("/");
    expect(currentNavHref("/about")).not.toBe("/");
  });

  it("marks a section from any page inside it", () => {
    expect(currentNavHref("/species")).toBe("/species");
    expect(currentNavHref("/species/DEMO-001/anguis-fragilis")).toBe("/species");
    expect(currentNavHref("/records")).toBe("/records");
    expect(currentNavHref("/explore")).toBe("/explore");
    expect(currentNavHref("/about")).toBe("/about");
  });

  it("does not match a different section that merely shares a prefix", () => {
    expect(currentNavHref("/speciesarium")).toBeNull();
    expect(currentNavHref("/records-archive")).toBeNull();
  });

  it("marks nothing on pages outside the primary navigation", () => {
    for (const path of ["/settings", "/accessibility", "/privacy", "/nowhere"]) {
      expect(currentNavHref(path)).toBeNull();
    }
  });
});
