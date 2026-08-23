import { Suspense, lazy } from "react";
import { SkipLink } from "../components/SkipLink";
import { ErrorBoundary } from "./ErrorBoundary";
import { Caveat } from "../components/Caveat";
import { SpeciesPanel } from "../features/species/SpeciesPanel";
import { CellSummaryTable } from "../features/species/CellSummaryTable";
import { RecordsTable } from "../features/species/RecordsTable";
import { LoadingState } from "../components/states/States";

// The map bundle (maplibre-gl) is heavy, so it is code-split and loaded lazily.
const DistributionMap = lazy(() => import("../features/map/DistributionMap"));

// P2 vertical slice: ONE species (Slow-worm) end-to-end — every panel is scoped by the
// SAME speciesId, so nothing silently shows all-species data. Runs against the MSW mock.
const SPECIES_ID = "anguis-fragilis";

export function App() {
  return (
    <>
      <SkipLink />
      <header className="app-header">
        <div className="row">
          <span className="brand">
            BRERC <span className="tag">Prototype</span>
          </span>
          <span className="sub">Wildlife of the West of England</span>
        </div>
      </header>

      <main id="main" className="explore-page">
        <span className="eyebrow">Distribution</span>
        <h1 className="page-title">Where wildlife has been recorded</h1>
        <p className="page-lead">
          A single-species slice of the atlas — its picture, where it has been recorded, and the same data as
          accessible tables.
        </p>

        <Caveat />

        <div className="slice-grid">
          <ErrorBoundary label="the species information">
            <SpeciesPanel speciesId={SPECIES_ID} />
          </ErrorBoundary>
          <ErrorBoundary label="the map">
            <Suspense
              fallback={
                <div className="map-card" style={{ display: "grid", placeItems: "center" }}>
                  <LoadingState label="the map" />
                </div>
              }
            >
              <DistributionMap speciesId={SPECIES_ID} />
            </Suspense>
          </ErrorBoundary>
        </div>

        <ErrorBoundary label="the distribution table">
          <CellSummaryTable speciesId={SPECIES_ID} />
        </ErrorBoundary>
        <ErrorBoundary label="the records table">
          <RecordsTable speciesId={SPECIES_ID} />
        </ErrorBoundary>
      </main>

      <footer className="app-footer">
        <div className="row">
          Data © BRERC · illustrative demo data · records reflect recording effort, not true distribution.
        </div>
      </footer>
    </>
  );
}
