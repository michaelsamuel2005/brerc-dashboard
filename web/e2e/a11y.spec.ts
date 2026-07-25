import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Verifies what jsdom cannot: the WebGL map mounts, both tables render, selection is truly
// bidirectional (map <-> table + card), selecting does not move the user's view, and there
// are no axe violations at desktop and mobile widths.
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

  test("table -> map: selecting a square updates the card without moving the button in view", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    const button = page.getByRole("button", { name: /ST5872/ });
    await button.scrollIntoViewIfNeeded();
    await button.focus();
    const topBefore = await button.evaluate((el) => el.getBoundingClientRect().top);
    await page.keyboard.press("Enter");
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".cell-card__id")).toHaveText("ST5872");
    const topAfter = await button.evaluate((el) => el.getBoundingClientRect().top);
    // scroll-anchoring may adjust scrollY, but the button the user is on must not visibly move.
    expect(Math.abs(topAfter - topBefore)).toBeLessThanOrEqual(20);
  });

  test("map -> table: clicking a square selects it without yanking the view, then clears", async ({ page, isMobile }) => {
    // Pixel-precise taps on the WebGL canvas are unreliable under mobile touch emulation
    // (a harness limitation, not an app bug); the map->table logic is viewport-independent
    // and is genuinely exercised on desktop.
    test.skip(!!isMobile, "canvas pixel-tap unreliable under mobile touch emulation");
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    const canvas = page.locator(".maplibregl-canvas").first();
    await expect(canvas).toBeVisible();
    const topBefore = await canvas.evaluate((el) => el.getBoundingClientRect().top);
    const bbox = await canvas.boundingBox();
    if (!bbox) throw new Error("no map canvas");
    const cx = bbox.x + bbox.width / 2;
    const cy = bbox.y + bbox.height / 2;
    await expect(async () => {
      await page.mouse.click(cx, cy);
      await expect(page.locator(".cell-card__id")).toHaveText(/ST\d/, { timeout: 1500 });
    }).toPass({ timeout: 15000 });
    const topAfter = await canvas.evaluate((el) => el.getBoundingClientRect().top);
    // the reviewer bug: clicking the map must not scroll the map out of view.
    expect(Math.abs(topAfter - topBefore)).toBeLessThanOrEqual(20);
    await page.getByRole("button", { name: "Clear selection" }).click();
    await expect(page.locator(".cell-card--empty")).toBeVisible();
  });
});
