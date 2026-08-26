import { expect, test } from "@playwright/test";

const SENSITIVE_SPECIES_ID = "SYNTH-E2E-1";
const ORDINARY_SPECIES_ID = "SYNTH-E2E-2";
const SENSITIVE_NAME = "Synthetic safety species";
const ORDINARY_NAME = "Synthetic ordinary species";
const MOCK_SPECIES = ["Adder", "Common lizard", "Slow-worm", "West European hedgehog"];

// A valid transparent PNG keeps MapLibre's raster source healthy without allowing a
// third-party basemap request to make this same-origin integration test flaky.
const TRANSPARENT_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL4WQAAAABJRU5ErkJggg==",
  "base64",
);
const CARTO_TILE = /^https:\/\/basemaps\.cartocdn\.com\/rastertiles\/voyager\//;

interface ApiProbeResult {
  readonly path: string;
  readonly status: number;
  readonly body: unknown;
}

interface SummaryResponse {
  readonly totalRecords: number;
  readonly totalSpecies: number;
}

interface SpeciesListResponse {
  readonly total: number;
  readonly items: readonly {
    readonly speciesId: string;
    readonly commonName: string | null;
  }[];
}

interface CellDistributionResponse {
  readonly cells: readonly {
    readonly cellId: string;
    readonly precisionMetres: number;
    readonly recordCount: number;
  }[];
}

interface RecordPageResponse {
  readonly total: number;
  readonly items: readonly unknown[];
  readonly publication: { readonly mode: string };
}

function bodyFor<T>(results: readonly ApiProbeResult[], path: string): T {
  const result = results.find((candidate) => candidate.path === path);
  if (!result) throw new Error(`Missing live API probe for ${path}`);
  return result.body as T;
}

test("the production build uses the protected live release, never browser mocks", async ({
  page,
}) => {
  const apiResponses: { status: number; path: string }[] = [];
  const failedRequests: string[] = [];
  const consoleErrors: string[] = [];
  const workerRequests: string[] = [];

  // This is the only request interception in the suite. API and application requests
  // always reach the real preview/FastAPI/PostgreSQL stack.
  await page.route(CARTO_TILE, (route) =>
    route.fulfill({
      status: 200,
      contentType: "image/png",
      body: TRANSPARENT_PNG,
      headers: { "cache-control": "public, max-age=3600" },
    }),
  );

  page.on("request", (request) => {
    if (request.url().includes("mockServiceWorker")) workerRequests.push(request.url());
  });
  page.on("requestfailed", (request) => failedRequests.push(request.url()));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith("/api/")) {
      apiResponses.push({ status: response.status(), path: `${url.pathname}${url.search}` });
    }
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(`PAGEERROR: ${String(error)}`));

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "The living record of the West of England" }),
  ).toBeVisible();
  await expect(page.locator(".kpi").filter({ hasText: "Records published" }).locator(".v"))
    .toHaveText("2");
  await expect(page.locator(".kpi").filter({ hasText: "Species" }).locator(".v"))
    .toHaveText("2");
  await expect(page.getByText(/prototype|illustrative demo data/i)).toHaveCount(0);

  const probePaths = [
    "/api/health",
    "/api/summary",
    "/api/species?sort=name-asc&page=1&pageSize=24",
    "/api/species?q=Synthetic%20ordinary&sort=name-asc&page=1&pageSize=24",
    `/api/summary?species=${SENSITIVE_SPECIES_ID}`,
    `/api/distribution/cells?species=${SENSITIVE_SPECIES_ID}`,
    `/api/distribution/cells?species=${SENSITIVE_SPECIES_ID}&year=2024`,
    `/api/distribution/cells?species=${SENSITIVE_SPECIES_ID}&year=2023`,
    `/api/records?species=${SENSITIVE_SPECIES_ID}`,
    `/api/records?species=${SENSITIVE_SPECIES_ID}&year=2024`,
    `/api/summary?species=${ORDINARY_SPECIES_ID}`,
    `/api/distribution/cells?species=${ORDINARY_SPECIES_ID}`,
    `/api/distribution/cells?species=${ORDINARY_SPECIES_ID}&year=2023`,
    `/api/distribution/cells?species=${ORDINARY_SPECIES_ID}&year=2024`,
    `/api/records?species=${ORDINARY_SPECIES_ID}`,
    `/api/records?species=${ORDINARY_SPECIES_ID}&year=2023`,
  ];
  const probes = await page.evaluate<ApiProbeResult[], string[]>(
    async (paths) =>
      Promise.all(
        paths.map(async (path) => {
          const response = await fetch(path, { headers: { Accept: "application/json" } });
          const text = await response.text();
          let body: unknown = text;
          try {
            body = JSON.parse(text) as unknown;
          } catch {
            // The status assertion below still reports a non-JSON proxy/API failure.
          }
          return { path, status: response.status, body };
        }),
      ),
    probePaths,
  );

  expect(probes.map(({ path, status }) => ({ path, status }))).toEqual(
    probePaths.map((path) => ({ path, status: 200 })),
  );

  const summary = bodyFor<SummaryResponse>(probes, "/api/summary");
  expect(summary).toMatchObject({ totalRecords: 2, totalSpecies: 2 });

  const species = bodyFor<SpeciesListResponse>(
    probes,
    "/api/species?sort=name-asc&page=1&pageSize=24",
  );
  expect(species.total).toBe(2);
  expect(species.items.map(({ speciesId }) => speciesId).sort()).toEqual(
    [SENSITIVE_SPECIES_ID, ORDINARY_SPECIES_ID].sort(),
  );
  expect(species.items.map(({ commonName }) => commonName).sort()).toEqual(
    [SENSITIVE_NAME, ORDINARY_NAME].sort(),
  );

  const searchedSpecies = bodyFor<SpeciesListResponse>(
    probes,
    "/api/species?q=Synthetic%20ordinary&sort=name-asc&page=1&pageSize=24",
  );
  expect(searchedSpecies).toMatchObject({
    total: 1,
    items: [{ speciesId: ORDINARY_SPECIES_ID, commonName: ORDINARY_NAME }],
  });

  const sensitiveCells = bodyFor<CellDistributionResponse>(
    probes,
    `/api/distribution/cells?species=${SENSITIVE_SPECIES_ID}&year=2024`,
  );
  expect(sensitiveCells.cells).toEqual([
    { cellId: "ST57", precisionMetres: 10_000, recordCount: 1 },
  ]);
  const ordinaryCells = bodyFor<CellDistributionResponse>(
    probes,
    `/api/distribution/cells?species=${ORDINARY_SPECIES_ID}&year=2023`,
  );
  expect(ordinaryCells.cells).toEqual([
    { cellId: "ST5972", precisionMetres: 1_000, recordCount: 1 },
  ]);
  for (const path of [
    `/api/distribution/cells?species=${SENSITIVE_SPECIES_ID}&year=2023`,
    `/api/distribution/cells?species=${ORDINARY_SPECIES_ID}&year=2024`,
  ]) {
    expect(bodyFor<CellDistributionResponse>(probes, path).cells).toEqual([]);
  }

  for (const path of [
    `/api/records?species=${SENSITIVE_SPECIES_ID}&year=2024`,
    `/api/records?species=${ORDINARY_SPECIES_ID}&year=2023`,
  ]) {
    const records = bodyFor<RecordPageResponse>(probes, path);
    expect(records).toMatchObject({
      total: 0,
      items: [],
      publication: { mode: "aggregates-only" },
    });
  }

  await page.goto("/#/species");
  await expect(page.getByRole("heading", { name: "Species directory" })).toBeVisible();
  await expect(page.getByText(SENSITIVE_NAME, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(ORDINARY_NAME, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/public demonstration catalogue/i)).toHaveCount(0);
  for (const name of MOCK_SPECIES) {
    await expect(page.getByText(name, { exact: true })).toHaveCount(0);
  }

  await page.getByRole("link", { name: `Explore ${SENSITIVE_NAME}` }).click();
  await expect(page.getByRole("heading", { name: SENSITIVE_NAME })).toBeVisible();
  const sensitiveRow = page.locator("tbody tr").filter({ hasText: "ST57" }).first();
  await expect(sensitiveRow).toContainText("10 km square");
  await expect(page.getByText("Individual records are not published.")).toBeVisible();

  await page.goto("/#/species");
  await page.getByRole("link", { name: `Explore ${ORDINARY_NAME}` }).click();
  await expect(page.getByRole("heading", { name: ORDINARY_NAME })).toBeVisible();
  const ordinaryRow = page.locator("tbody tr").filter({ hasText: "ST5972" }).first();
  await expect(ordinaryRow).toContainText("1 km square");

  const serviceWorkerState = await page.evaluate(async () => {
    if (!("serviceWorker" in navigator)) return { controlled: false, registrations: 0 };
    const registrations = await navigator.serviceWorker.getRegistrations();
    return {
      controlled: navigator.serviceWorker.controller !== null,
      registrations: registrations.length,
    };
  });
  expect(serviceWorkerState).toEqual({ controlled: false, registrations: 0 });
  expect(workerRequests).toEqual([]);
  expect(apiResponses.filter(({ status }) => status !== 200)).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
