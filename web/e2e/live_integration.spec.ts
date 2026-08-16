import { expect, test } from "@playwright/test";

/**
 * Steps 7 and 11 of the test plan: the built front end, mocks disabled,
 * against the real API and a real publication database.
 *
 * The production build gates MSW on `import.meta.env.DEV`, so `vite preview`
 * serves an app with no mock layer at all. Every request below is a genuine
 * round trip to FastAPI and PostgreSQL/PostGIS, which is the only way to catch
 * a query parameter the server ignores, a CORS origin that was never listed,
 * or a route that only resolves against fixture data.
 */
test("the built app renders real published data with no mock layer", async ({ page }) => {
  const responses: string[] = [];
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("requestfailed", (r) => failedRequests.push(r.url()));
  page.on("response", (r) => {
    if (r.url().includes("/api/")) responses.push(`${r.status()} ${new URL(r.url()).pathname}`);
  });
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
  });
  page.on("pageerror", (e) => consoleErrors.push(`PAGEERROR ${String(e).slice(0, 200)}`));

  await page.goto("/");
  await page.waitForLoadState("networkidle");

  // Landing route resolves to the directory, and the species the release
  // actually publishes is listed — not a fixture species.
  await expect(page.getByRole("heading", { name: /Species directory/i })).toBeVisible();
  await expect(page.getByText("Synthetic alpha").first()).toBeVisible({ timeout: 15_000 });

  // Drill into that species: detail, map cells and records all come from the API.
  await page.getByRole("link", { name: /^Explore / }).first().click();
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: /Synthetic alpha/i })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText("ST5872").first()).toBeVisible({ timeout: 15_000 });

  // The basemap is fetched from a third-party tile host. This environment has
  // no outbound network, so those requests fail here and would succeed in a
  // deployment. Classify rather than ignore: anything failing that belongs to
  // the app or the API is a real defect and must still fail the test.
  const ownOrigin = (url: string) =>
    url.startsWith("http://127.0.0.1:4173") || url.startsWith("http://127.0.0.1:8000");
  const externalFailures = failedRequests.filter((u) => !ownOrigin(u));
  const ownFailures = failedRequests.filter(ownOrigin);

  console.log("API RESPONSES  :", JSON.stringify([...new Set(responses)]));
  console.log("OWN FAILURES   :", JSON.stringify(ownFailures));
  console.log("EXTERNAL (env) :", JSON.stringify([...new Set(externalFailures.map((u) => new URL(u).host))]));
  console.log("CONSOLE ERRORS :", JSON.stringify([...new Set(consoleErrors)].slice(0, 4)));
  await page.screenshot({ path: "/home/claude/live-integration.png", fullPage: true });

  // No API call may fail, and a schema rejection surfaces as a console error,
  // so together these assert the contract holds at runtime.
  expect(responses.filter((r) => !r.startsWith("200"))).toEqual([]);
  expect(ownFailures, "the app and API must serve every request they are asked for").toEqual([]);
  // A schema rejection surfaces as a console error from our own code, so
  // exclude only the environmental resource failures, not error text generally.
  expect(
    consoleErrors.filter((e) => !e.includes("Failed to load resource")),
    "no application error may reach the console",
  ).toEqual([]);
});
