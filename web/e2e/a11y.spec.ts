import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Verifies the things jsdom cannot: the WebGL map actually mounts, both accessible tables
// render, and there are no axe violations at desktop and mobile widths.
test.describe("BRERC P2 slice", () => {
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
    // The app mounts only after the MSW worker starts, so wait for it to render
    // before tabbing — otherwise the first Tab races an empty DOM.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: /skip/i })).toBeFocused();
  });

  test("the map working area uses available desktop space without changing the viewport proportion", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await expect(page.locator(".maplibregl-canvas").first()).toBeVisible();

    const mainBox = await page.locator("main.explore-page").boundingBox();
    const mapBox = await page.locator(".map-card").boundingBox();

    expect(mainBox).not.toBeNull();
    expect(mapBox).not.toBeNull();
    expect(mainBox!.width).toBeGreaterThan(1100);
    expect(mapBox!.height).toBeGreaterThan(520);
    expect(mapBox!.height).toBeLessThanOrEqual(630);
  });
});
