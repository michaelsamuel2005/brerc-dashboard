import { Suspense, lazy } from "react";
import { Link, useParams } from "react-router-dom";
import { Caveat } from "../../components/Caveat";
import { LoadingState } from "../../components/states/States";
import { ErrorBoundary } from "../../app/ErrorBoundary";
import { SpeciesPanel } from "./SpeciesPanel";
import { CellSummaryTable } from "./CellSummaryTable";
import { RecordsTable } from "./RecordsTable";

const DistributionMap = lazy(() => import("../map/DistributionMap"));

// One species end-to-end, scoped by the speciesId route param — the same slice App used
// to render for a single hard-coded species, now reachable at /species/:speciesId.
export function SpeciesDetailPage() {
  const { speciesId } = useParams<{ speciesId: string }>();

  if (!speciesId) return <div role="alert">Sorry — no species was specified.</div>;

  return (
    <>
      <p className="page-lead">
        <Link to="/">← Back to all species</Link>
      </p>

      <Caveat />

      <div className="slice-grid">
        <ErrorBoundary label="the species information">
          <SpeciesPanel speciesId={speciesId} />
        </ErrorBoundary>
        <ErrorBoundary label="the map">
          <Suspense
            fallback={
              <div className="map-card" style={{ display: "grid", placeItems: "center" }}>
                <LoadingState label="the map" />
              </div>
            }
          >
            <DistributionMap speciesId={speciesId} />
          </Suspense>
        </ErrorBoundary>
      </div>

      <ErrorBoundary label="the distribution table">
        <CellSummaryTable speciesId={speciesId} />
      </ErrorBoundary>
      <ErrorBoundary label="the records table">
        <RecordsTable speciesId={speciesId} />
      </ErrorBoundary>
    </>
  );
}
