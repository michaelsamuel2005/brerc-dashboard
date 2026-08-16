import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Verifies what jsdom cannot: the WebGL map mounts, both tables render, selection is truly
// bidirectional (map <-> table + card), selecting does not move the user's view, and there
// are no axe violations at desktop and mobile widths.
test.describe("BRERC P3 slice", () => {
  // "/" is the overview page (a landing route, no map). The map, the grid-square table,
// the selected-cell card and the year chart live on a species page, so these tests name
// that route explicitly instead of relying on what "/" happens to redirect to. That
// coupling is what broke them: the redirect changed and nothing here noticed.
const SPECIES_ROUTE = "/#/species/DEMO-001/anguis-fragilis";

test("species directory deep-link searches and opens a coherent species route", async ({ page }) => {
    await page.goto("/#/species");
    await expect(page.getByRole("heading", { name: "Species directory" })).toBeVisible();
    await page.getByLabel(/Search by common or scientific name/i).fill("Vipera");
    await page.getByRole("button", { name: "Search" }).click();
    const adder = page.getByRole("link", { name: /Explore Adder/i });
    await expect(adder).toBeVisible();
    await adder.click();
    await expect(page).toHaveURL(/#\/species\/DEMO-002\/vipera-berus$/);
    await expect(page.getByRole("heading", { name: "Adder", level: 2 })).toBeVisible();
    await expect(page.getByText("Vipera berus")).toBeVisible();
  });

  test("renders map + both tables with no axe violations", async ({ page }) => {
    await page.goto(SPECIES_ROUTE);
    await expect(page.getByRole("heading", { name: /Slow-worm/ })).toBeVisible();
    await expect(page.locator(".maplibregl-canvas").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: /Distribution by grid square/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Published records/ })).toBeVisible();
    // Axe's installed rules do not implement target-size geometry; the dedicated
    // collector supplies SC 2.5.8. Keep every other available 2.2 AA-tagged rule here.
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(results.violations).toEqual([]);
  });

  test("keyboard: the skip link is the first focus stop", async ({ page }) => {
    await page.goto(SPECIES_ROUTE);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: /skip/i })).toBeFocused();
  });

  test("table -> map: selecting a square updates the card without moving the button in view", async ({ page }) => {
    await page.goto(SPECIES_ROUTE);
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
    await page.goto(SPECIES_ROUTE);
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

  test("year filter: selecting a year cross-filters the map, tables and card, then resets", async ({ page }) => {
    await page.goto(SPECIES_ROUTE);
    await page.waitForLoadState("networkidle");
    // The chart's accessible equivalent is a disclosure containing a button per year.
    await page.getByRole("group", { name: /Distribution by grid square/ }).waitFor();
    const squaresNote = page.locator("#cells-heading + p");
    await expect(squaresNote).toContainText("186 records");
    await page.getByRole("heading", { name: /Records submitted by year/ }).scrollIntoViewIfNeeded();
    await page.locator(".chart-table > summary").click();
    const yearButton = page.locator(".chart-table").getByRole("button", { name: /2024/ });
    await yearButton.click();
    await expect(yearButton).toHaveAttribute("aria-pressed", "true");
    // The grid-square table is now filtered to that year (fewer than the 186 all-year total).
    await expect(squaresNote).toContainText("Filtered to 2024");
    await expect(squaresNote).not.toContainText("186 records");
    // Toggle back to all years.
    await yearButton.click();
    await expect(squaresNote).toContainText("186 records");
  });
});
