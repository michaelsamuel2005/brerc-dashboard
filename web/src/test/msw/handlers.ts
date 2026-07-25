import { http, HttpResponse } from "msw";
import {
  cellsFixture,
  healthFixture,
  provenanceFixture,
  recordsFixture,
  speciesDetailFixture,
  speciesListFixture,
  summaryFixture,
} from "../fixtures";

// MSW handlers implementing the apiContract (A11). Dev + tests only — never shipped.
// distribution/cells + records HONOUR ?species=: an unscoped/wrong-species request returns
// EMPTY, so a missing client-side filter is visible.
const DEMO_SPECIES = "anguis-fragilis";

export const handlers = [
  http.get("*/api/health", () => HttpResponse.json(healthFixture)),
  http.get("*/api/summary", () => HttpResponse.json(summaryFixture)),
  http.get("*/api/species", () => HttpResponse.json(speciesListFixture)),
  http.get("*/api/species/:speciesId", () => HttpResponse.json(speciesDetailFixture)),
  http.get("*/api/distribution/cells", ({ request }) => {
    const species = new URL(request.url).searchParams.get("species");
    if (species !== DEMO_SPECIES) return HttpResponse.json({ cells: [] });
    return HttpResponse.json(cellsFixture);
  }),
  http.get("*/api/records", ({ request }) => {
    const species = new URL(request.url).searchParams.get("species");
    if (species !== DEMO_SPECIES) return HttpResponse.json({ ...recordsFixture, items: [], total: 0 });
    return HttpResponse.json(recordsFixture);
  }),
  http.get("*/api/meta/provenance", () => HttpResponse.json(provenanceFixture)),
];
