import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

test.describe('full-dashboard UI corrections', () => {
  test('overview removes the prototype badge and uses the available width without overflow', async ({ page }) => {
    await page.goto('/?species=DEMO-003#/');
    await expect(page.getByRole('heading', { name: 'The living record of the West of England' })).toBeVisible();

    await expect(page.getByRole('link', { name: 'BRERC home' })).toHaveText('BRERC');
    await expect(page.getByText(/prototype/i)).toHaveCount(0);

    const layout = await page.evaluate(() => {
      const main = document.querySelector('main')?.getBoundingClientRect();
      return {
        viewportWidth: window.innerWidth,
        mainWidth: main?.width ?? 0,
        noHorizontalOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      };
    });
    expect(layout.noHorizontalOverflow).toBe(true);
    if (layout.viewportWidth >= 1000) expect(layout.mainWidth).toBeGreaterThanOrEqual(1200);
  });

  test('explore has a larger map and an accessible collapsed map key', async ({ page }) => {
    await page.goto('/?species=DEMO-003#/explore');
    const map = page.locator('.explore-layout .map-card');
    await expect(map).toBeVisible();
    await expect(page.locator('.maplibregl-canvas')).toBeVisible();

    const key = page.getByRole('button', { name: 'Map key' });
    const content = page.locator('#map-key-content');
    await expect(key).toHaveAttribute('aria-expanded', 'false');
    await expect(content).toBeHidden();
    await key.press('Enter');
    await expect(key).toHaveAttribute('aria-expanded', 'true');
    await expect(content).toBeVisible();
    await expect(content).toContainText('The squares are translucent so the map remains visible.');

    const layout = await page.evaluate(() => {
      const card = document.querySelector('.explore-layout .map-card')?.getBoundingClientRect();
      return {
        viewportWidth: window.innerWidth,
        mapWidth: card?.width ?? 0,
        mapHeight: card?.height ?? 0,
        noHorizontalOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      };
    });
    expect(layout.noHorizontalOverflow).toBe(true);
    expect(layout.mapHeight).toBeGreaterThanOrEqual(layout.viewportWidth >= 1000 ? 640 : 480);
    if (layout.viewportWidth >= 1000) expect(layout.mapWidth).toBeGreaterThanOrEqual(850);

    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await key.press('Space');
    await expect(key).toHaveAttribute('aria-expanded', 'false');
    await expect(content).toBeHidden();
  });
});
