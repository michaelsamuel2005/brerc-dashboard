import { Suspense, lazy } from "react";
import { SkipLink } from "../components/SkipLink";
import { ErrorBoundary } from "./ErrorBoundary";
import { Caveat } from "../components/Caveat";
import { SpeciesPanel } from "../features/species/SpeciesPanel";
import { RecordsTable } from "../features/species/RecordsTable";
import { LoadingState } from "../components/states/States";

// The map bundle (maplibre-gl) is heavy, so it is code-split and loaded lazily.
const DistributionMap = lazy(() => import("../features/map/DistributionMap"));

// P2 vertical slice: ONE species (Slow-worm) shown end-to-end — species panel, the
// honest distribution map, and the accessible records table — against the MSW mock.
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

      <main id="main">
        <span className="eyebrow">Distribution</span>
        <h1 className="page-title">Where wildlife has been recorded</h1>
        <p className="page-lead">
          A single-species slice of the atlas — its picture, where it has been recorded, and the same data as an
          accessible table.
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
              <DistributionMap />
            </Suspense>
          </ErrorBoundary>
        </div>

        <ErrorBoundary label="the records table">
          <RecordsTable />
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
