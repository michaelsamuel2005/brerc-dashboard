import { delay, http, HttpResponse } from "msw";
import {
  buildSpeciesListPage,
  cellsForSpecies,
  healthFixture,
  provenanceFixture,
  recordsForSpecies,
  speciesDetailFor,
  speciesSummaryFor,
  summaryFixture,
} from "../fixtures";
import { SpeciesSortSchema } from "../../lib/api/schemas";

// MSW handlers implementing the apiContract (A11). Dev + tests only — never shipped.
// distribution/cells + records honour ?species= (unscoped ⇒ EMPTY, so a missing client
// filter is visible) and ?year= (so the chart's year filter genuinely cross-filters, with
// every count derived from the same cell×year matrix).
const A11Y_SCENARIO_COOKIE = "brerc-a11y-scenario";
type A11yScenario = "loading" | "empty" | "error";

function a11yScenario(request: Request): A11yScenario | null {
  const cookie = request.headers.get("cookie") ?? "";
  const value = cookie
    .split(";")
    .map((part) => part.trim().split("=", 2))
    .find(([name]) => name === A11Y_SCENARIO_COOKIE)?.[1];
  return value === "loading" || value === "empty" || value === "error" ? value : null;
}

function yearParam(request: Request): number | undefined {
  const raw = new URL(request.url).searchParams.get("year");
  if (raw === null || raw === "") return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}
const speciesParam = (request: Request) => new URL(request.url).searchParams.get("species");

function positiveIntegerParam(
  searchParams: URLSearchParams,
  name: string,
  fallback: number,
): number | null {
  const raw = searchParams.get(name);
  if (raw === null || raw === "") return fallback;
  const value = Number(raw);
  return Number.isInteger(value) && value > 0 ? value : null;
}

export const handlers = [
  http.get("*/api/health", () => HttpResponse.json(healthFixture)),
  http.get("*/api/summary", ({ request }) => {
    const speciesId = speciesParam(request);
    if (speciesId === null) return HttpResponse.json(summaryFixture);
    const summary = speciesSummaryFor(speciesId);
    return summary
      ? HttpResponse.json(summary)
      : HttpResponse.json({ error: "Unknown synthetic species" }, { status: 404 });
  }),
  http.get("*/api/species", ({ request }) => {
    const searchParams = new URL(request.url).searchParams;
    const page = positiveIntegerParam(searchParams, "page", 1);
    const pageSize = positiveIntegerParam(searchParams, "pageSize", 20);
    const parsedSort = SpeciesSortSchema.safeParse(searchParams.get("sort") ?? "name-asc");

    if (page === null || pageSize === null || pageSize > 50 || !parsedSort.success) {
      return HttpResponse.json({ error: "Invalid species directory query" }, { status: 400 });
    }

    return HttpResponse.json(
      buildSpeciesListPage({
        q: searchParams.get("q") ?? "",
        ...(searchParams.get("group") ? { group: searchParams.get("group") ?? undefined } : {}),
        sort: parsedSort.data,
        page,
        pageSize,
      }),
    );
  }),
  http.get("*/api/species/:speciesId", ({ params }) => {
    const speciesId = String(params.speciesId);
    const detail = speciesDetailFor(speciesId);
    return detail
      ? HttpResponse.json(detail)
      : HttpResponse.json({ error: "Unknown synthetic species" }, { status: 404 });
  }),
  http.get("*/api/distribution/cells", async ({ request }) => {
    // Playwright sets a same-origin cookie before navigation. Handling the scenario
    // inside MSW is deterministic; page.route cannot reliably beat a service worker.
    const scenario = a11yScenario(request);
    if (scenario === "loading") await delay("infinite");
    if (scenario === "empty") {
      return HttpResponse.json({ verificationAvailable: true, cells: [] });
    }
    if (scenario === "error") {
      return HttpResponse.json(
        { error: "Deliberate accessibility-test failure" },
        { status: 503 },
      );
    }
    const speciesId = speciesParam(request);
    if (speciesId === null) {
      return HttpResponse.json({ verificationAvailable: true, cells: [] });
    }
    return HttpResponse.json({
      verificationAvailable: true,
      cells: cellsForSpecies(speciesId, yearParam(request)),
    });
  }),
  http.get("*/api/records", ({ request }) => {
    const searchParams = new URL(request.url).searchParams;
    const page = positiveIntegerParam(searchParams, "page", 1);
    const pageSize = positiveIntegerParam(searchParams, "pageSize", 20);
    if (page === null || pageSize === null || pageSize > 50) {
      return HttpResponse.json({ error: "Invalid records query" }, { status: 400 });
    }
    const speciesId = speciesParam(request);
    if (speciesId === null) {
      // Even an unscoped empty response must declare the publication policy. An
      // empty list alone cannot distinguish "no records" from "rows withheld".
      return HttpResponse.json(recordsForSpecies("__unscoped__", undefined, page, pageSize));
    }
    return HttpResponse.json(recordsForSpecies(speciesId, yearParam(request), page, pageSize));
  }),
  http.get("*/api/meta/provenance", () => HttpResponse.json(provenanceFixture)),
];
