import { Suspense, lazy, useState } from "react";
import { Link } from "wouter";
import { Caveat } from "../components/Caveat";
import { LoadingState } from "../components/states/States";
import { CellSummaryTable } from "../features/species/CellSummaryTable";
import { RecordsTable } from "../features/species/RecordsTable";
import { SelectedCellCard } from "../features/species/SelectedCellCard";
import { SpeciesPanel } from "../features/species/SpeciesPanel";
import { ErrorBoundary } from "./ErrorBoundary";

// MapLibre remains code-split: opening the species directory does not download WebGL code.
const DistributionMap = lazy(() => import("../features/map/DistributionMap"));
const RecordsByYearChart = lazy(() => import("../features/chart/RecordsByYearChart"));

export function SpeciesDashboard({ speciesId }: { speciesId: string }) {
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);

  function handleSelectYear(year: number | null) {
    setSelectedYear(year);
    setSelectedCellId(null);
  }

  return (
    <main id="main">
      <Link className="back-link" href="/species">← All species</Link>
      <span className="eyebrow">Distribution</span>
      <h1 className="page-title" tabIndex={-1}>Where wildlife has been recorded</h1>
      <p className="page-lead">
        Explore one species through its distribution map, accessible data tables and yearly records.
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
              <DistributionMap
                speciesId={speciesId}
                year={selectedYear}
                selectedCellId={selectedCellId}
                onSelectCell={setSelectedCellId}
              />
            </Suspense>
          </ErrorBoundary>
          <ErrorBoundary label="the selected-cell details">
            <SelectedCellCard
              speciesId={speciesId}
              year={selectedYear}
              selectedCellId={selectedCellId}
              onClear={() => setSelectedCellId(null)}
            />
          </ErrorBoundary>
        </div>
        <ErrorBoundary label="the species information">
          <SpeciesPanel speciesId={speciesId} />
        </ErrorBoundary>
      </div>

      <ErrorBoundary label="the distribution table">
        <CellSummaryTable
          speciesId={speciesId}
          year={selectedYear}
          selectedCellId={selectedCellId}
          onSelectCell={setSelectedCellId}
        />
      </ErrorBoundary>
      <ErrorBoundary label="the yearly chart">
        <Suspense fallback={<div className="state"><LoadingState label="the yearly chart" /></div>}>
          <RecordsByYearChart
            speciesId={speciesId}
            selectedYear={selectedYear}
            onSelectYear={handleSelectYear}
          />
        </Suspense>
      </ErrorBoundary>
      <ErrorBoundary label="the records table">
        <RecordsTable speciesId={speciesId} year={selectedYear} />
      </ErrorBoundary>
    </main>
  );
}
