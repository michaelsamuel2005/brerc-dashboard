import { Suspense, lazy, useState } from "react";
import { SkipLink } from "../components/SkipLink";
import { ErrorBoundary } from "./ErrorBoundary";
import { Caveat } from "../components/Caveat";
import { SpeciesPanel } from "../features/species/SpeciesPanel";
import { SelectedCellCard } from "../features/species/SelectedCellCard";
import { CellSummaryTable } from "../features/species/CellSummaryTable";
import { RecordsTable } from "../features/species/RecordsTable";
import { LoadingState } from "../components/states/States";

// The map bundle (maplibre-gl) is heavy, so it is code-split and loaded lazily.
const DistributionMap = lazy(() => import("../features/map/DistributionMap"));

// One species (Slow-worm), map-FIRST: the map + its selected-cell card lead the page (and
// the DOM), so on mobile the map is immediately reachable; species info is secondary. The
// map, the cell table and the card share ONE selectedCellId.
const SPECIES_ID = "anguis-fragilis";

export function App() {
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);

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
          A single-species slice of the atlas — where it has been recorded, the same data as accessible tables, and its
          picture.
        </p>

        <Caveat />

        <div className="slice-grid">
          <div className="map-col">
            <ErrorBoundary label="the map">
              <Suspense
                fallback={
                  <div className="map-card" style={{ display: "grid", placeItems: "center" }}>
                    <LoadingState label="the map" />
                  </div>
                }
              >
                <DistributionMap speciesId={SPECIES_ID} selectedCellId={selectedCellId} onSelectCell={setSelectedCellId} />
              </Suspense>
            </ErrorBoundary>
            <ErrorBoundary label="the selected-cell details">
              <SelectedCellCard speciesId={SPECIES_ID} selectedCellId={selectedCellId} onClear={() => setSelectedCellId(null)} />
            </ErrorBoundary>
          </div>
          <ErrorBoundary label="the species information">
            <SpeciesPanel speciesId={SPECIES_ID} />
          </ErrorBoundary>
        </div>

        <ErrorBoundary label="the distribution table">
          <CellSummaryTable speciesId={SPECIES_ID} selectedCellId={selectedCellId} onSelectCell={setSelectedCellId} />
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
