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
export const handlers = [
  http.get("*/api/health", () => HttpResponse.json(healthFixture)),
  http.get("*/api/summary", () => HttpResponse.json(summaryFixture)),
  http.get("*/api/species", () => HttpResponse.json(speciesListFixture)),
  http.get("*/api/species/:speciesId", () => HttpResponse.json(speciesDetailFixture)),
  http.get("*/api/distribution/cells", () => HttpResponse.json(cellsFixture)),
  http.get("*/api/records", () => HttpResponse.json(recordsFixture)),
  http.get("*/api/meta/provenance", () => HttpResponse.json(provenanceFixture)),
];
