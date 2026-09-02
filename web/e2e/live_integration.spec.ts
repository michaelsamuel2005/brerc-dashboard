import { expect, test } from "@playwright/test";

const SENSITIVE_SPECIES_ID = "SYNTH-E2E-1";
const REMOVED_SPECIES_ID = "SYNTH-E2E-2";
const PUBLISHED_SPECIES_ID = "SYNTH-E2E-3";
const SENSITIVE_NAME = "Synthetic safety species";
const REMOVED_NAME = "Synthetic ordinary species";
const PUBLISHED_NAME = "Synthetic unlicensed species";
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

interface ProvenanceResponse {
  readonly releaseId: string;
  readonly datasetVersion: string;
  readonly recordTotal: number;
  readonly sensitivityPolicy: {
    readonly protectedRecordsMode: string;
    readonly publishedLocationTiersMetres: readonly number[];
    readonly note: string;
  };
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
    .toHaveText("1");
  await expect(page.locator(".kpi").filter({ hasText: "Species" }).locator(".v"))
    .toHaveText("1");
  await expect(page.getByText(/prototype|illustrative demo data/i)).toHaveCount(0);

  const probePaths = [
    "/api/health",
    "/api/meta/provenance",
    "/api/summary",
    "/api/species?sort=name-asc&page=1&pageSize=24",
    "/api/species?q=Synthetic%20unlicensed&sort=name-asc&page=1&pageSize=24",
    `/api/distribution/cells?species=${SENSITIVE_SPECIES_ID}`,
    `/api/distribution/cells?species=${SENSITIVE_SPECIES_ID}&year=2024`,
    `/api/distribution/cells?species=${SENSITIVE_SPECIES_ID}&year=2023`,
    `/api/records?species=${SENSITIVE_SPECIES_ID}`,
    `/api/records?species=${SENSITIVE_SPECIES_ID}&year=2024`,
    `/api/summary?species=${PUBLISHED_SPECIES_ID}`,
    `/api/distribution/cells?species=${PUBLISHED_SPECIES_ID}`,
    `/api/distribution/cells?species=${PUBLISHED_SPECIES_ID}&year=2022`,
    `/api/distribution/cells?species=${PUBLISHED_SPECIES_ID}&year=2024`,
    `/api/records?species=${PUBLISHED_SPECIES_ID}`,
    `/api/records?species=${PUBLISHED_SPECIES_ID}&year=2022`,
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
  expect(summary).toMatchObject({ totalRecords: 1, totalSpecies: 1 });

  const provenance = bodyFor<ProvenanceResponse>(probes, "/api/meta/provenance");
  expect(provenance.releaseId).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
  );
  expect(provenance.datasetVersion).not.toHaveLength(0);
  expect(provenance).toMatchObject({
    recordTotal: 1,
    sensitivityPolicy: {
      protectedRecordsMode: "withheld",
      publishedLocationTiersMetres: [1_000],
    },
  });
  expect(provenance.sensitivityPolicy.note).not.toMatch(/generali[sz]/i);

  const species = bodyFor<SpeciesListResponse>(
    probes,
    "/api/species?sort=name-asc&page=1&pageSize=24",
  );
  expect(species.total).toBe(1);
  expect(species.items).toEqual([
    expect.objectContaining({ speciesId: PUBLISHED_SPECIES_ID, commonName: PUBLISHED_NAME }),
  ]);
  expect(species.items.map(({ speciesId }) => speciesId)).not.toContain(SENSITIVE_SPECIES_ID);
  expect(species.items.map(({ speciesId }) => speciesId)).not.toContain(REMOVED_SPECIES_ID);

  const searchedSpecies = bodyFor<SpeciesListResponse>(
    probes,
    "/api/species?q=Synthetic%20unlicensed&sort=name-asc&page=1&pageSize=24",
  );
  expect(searchedSpecies).toMatchObject({
    total: 1,
    items: [{ speciesId: PUBLISHED_SPECIES_ID, commonName: PUBLISHED_NAME }],
  });

  const sensitiveCells = bodyFor<CellDistributionResponse>(
    probes,
    `/api/distribution/cells?species=${SENSITIVE_SPECIES_ID}&year=2024`,
  );
  expect(sensitiveCells.cells).toEqual([]);
  const ordinaryCells = bodyFor<CellDistributionResponse>(
    probes,
    `/api/distribution/cells?species=${PUBLISHED_SPECIES_ID}&year=2022`,
  );
  expect(ordinaryCells.cells).toEqual([
    { cellId: "ST5872", precisionMetres: 1_000, recordCount: 1 },
  ]);
  for (const path of [
    `/api/distribution/cells?species=${SENSITIVE_SPECIES_ID}&year=2023`,
    `/api/distribution/cells?species=${PUBLISHED_SPECIES_ID}&year=2024`,
  ]) {
    expect(bodyFor<CellDistributionResponse>(probes, path).cells).toEqual([]);
  }

  for (const path of [
    `/api/records?species=${SENSITIVE_SPECIES_ID}&year=2024`,
    `/api/records?species=${PUBLISHED_SPECIES_ID}&year=2022`,
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
  await expect(page.getByText(SENSITIVE_NAME, { exact: true })).toHaveCount(0);
  await expect(page.getByText(REMOVED_NAME, { exact: true })).toHaveCount(0);
  await expect(page.getByText(PUBLISHED_NAME, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/public demonstration catalogue/i)).toHaveCount(0);
  for (const name of MOCK_SPECIES) {
    await expect(page.getByText(name, { exact: true })).toHaveCount(0);
  }

  await page.getByRole("link", { name: `Explore ${PUBLISHED_NAME}` }).click();
  await expect(page.getByRole("heading", { name: PUBLISHED_NAME })).toBeVisible();
  const ordinaryRow = page.locator("tbody tr").filter({ hasText: "ST5872" }).first();
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
