import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Verifies the things jsdom cannot: the WebGL map mounts, both tables render, selection is
// truly bidirectional (map <-> table + card), a map click does NOT scroll the page, and
// there are no axe violations at desktop and mobile widths.
test.describe("BRERC P3 slice", () => {
  test("renders map + both tables with no axe violations", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Slow-worm/ })).toBeVisible();
    await expect(page.locator(".maplibregl-canvas").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: /Distribution by grid square/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Sample of individual records/ })).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(results.violations).toEqual([]);
  });

  test("keyboard: the skip link is the first focus stop", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: /skip/i })).toBeFocused();
  });

  test("table -> map: selecting a square syncs the card and does NOT scroll the page", async ({ page }) => {
    await page.goto("/");
    const button = page.getByRole("button", { name: /ST5872/ });
    await button.scrollIntoViewIfNeeded();
    await button.focus();
    const before = await page.evaluate(() => window.scrollY);
    await page.keyboard.press("Enter");
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".cell-card").getByRole("heading", { name: "ST5872" })).toBeVisible();
    expect(await page.evaluate(() => window.scrollY)).toBe(before);
  });

  test("map -> table: clicking a square selects it without a page jump, then clears", async ({ page }) => {
    await page.goto("/");
    const canvas = page.locator(".maplibregl-canvas").first();
    await expect(canvas).toBeVisible();
    await page.waitForTimeout(900); // let the cell layer paint
    const before = await page.evaluate(() => window.scrollY);
    const bbox = await canvas.boundingBox();
    if (!bbox) throw new Error("no map canvas");
    await page.mouse.click(bbox.x + bbox.width / 2, bbox.y + bbox.height / 2);
    await expect(page.locator(".cell-card h3")).toBeVisible(); // map selection reflected in the card
    expect(await page.evaluate(() => window.scrollY)).toBe(before); // the exact reviewer bug: no page jump
    await page.getByRole("button", { name: /clear selection/i }).click();
    await expect(page.locator(".cell-card--empty")).toBeVisible();
  });
});
