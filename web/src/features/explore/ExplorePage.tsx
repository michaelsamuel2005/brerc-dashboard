import { Suspense, lazy, useMemo, useState } from "react";
import { Link, useSearchParams } from "wouter";
import { Caveat } from "../../components/Caveat";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";
import { ErrorBoundary } from "../../app/ErrorBoundary";
import { toAsyncState, useDistributionCells, useSpeciesList } from "../../lib/api";
import { MAX_PAGE_SIZE } from "../../lib/api/schemas";
import { gridRefToPolygon } from "../../lib/geo/osgb";
import { cellsWithinRadius, radiusIsFinerThanData } from "../../lib/geo/radius";

const DistributionMap = lazy(() => import("../map/DistributionMap"));

/** Offered radii. Nothing below 500 m: a finer question cannot get a finer answer. */
const RADII = [500, 1000, 2000, 5000] as const;
const DEFAULT_RADIUS = 1000;

function formatNumber(value: number): string {
  return value.toLocaleString("en-GB");
}

function formatDistance(metres: number): string {
  return metres >= 1000 ? `${(metres / 1000).toFixed(1)} km` : `${Math.round(metres)} m`;
}

function describeResolution(metres: number): string {
  return metres >= 1000 ? `${metres / 1000} km square` : `${metres} m square`;
}

/**
 * Explore — the map-first page, with a "what has been recorded near here" query.
 *
 * The interaction is BAM's: place a point, choose a radius, get what is nearby. The
 * representation is ours and stays ours. BAM's circle is the buffer a user draws, and
 * its results are a list; drawing our own DATA as circles would put a centre on every
 * record and quietly assert a precision that generalisation exists to remove. So the
 * circle here is the question, and the squares remain the answer.
 *
 * The whole query runs in the browser, over cells the map already had. No new endpoint,
 * no finer data requested, and nothing about where the visitor pointed is sent anywhere.
 */
export default function ExplorePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [centre, setCentre] = useState<[number, number] | null>(null);
  const [radiusMetres, setRadiusMetres] = useState<number>(DEFAULT_RADIUS);
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);

  const speciesQuery = useSpeciesList({ sort: "records-desc", page: 1, pageSize: MAX_PAGE_SIZE });
  const speciesState = toAsyncState(speciesQuery);
  const options = speciesState.status === "ready" ? speciesState.data.items : [];
  const requested = searchParams.get("species") ?? "";
  const activeId = options.some((item) => item.speciesId === requested)
    ? requested
    : options[0]?.speciesId ?? "";
  const active = options.find((item) => item.speciesId === activeId) ?? null;
  const activeName = active ? (active.commonName ?? active.scientificName) : "";

  const cellsQuery = useDistributionCells(activeId ? { species: activeId } : undefined);
  const cellsState = toAsyncState(cellsQuery, (data) => data.cells.length === 0);

  // Derive each cell's polygon from its validated id — the same rule the map follows,
  // so the query can never be run against geometry the server supplied.
  const geometry = useMemo(() => {
    if (cellsState.status !== "ready") return [];
    return cellsState.data.cells.flatMap((cell) => {
      const ring = gridRefToPolygon(cell.cellId);
      return ring
        ? [{
            cellId: cell.cellId,
            ring,
            precisionMetres: cell.precisionMetres,
            recordCount: cell.recordCount,
          }]
        : [];
    });
  }, [cellsState]);

  const nearby = useMemo(
    () => (centre ? cellsWithinRadius(geometry, centre, radiusMetres) : []),
    [geometry, centre, radiusMetres],
  );
  const coarserThanQuery = centre !== null && radiusIsFinerThanData(radiusMetres, nearby);
  const nearbyRecords = nearby.reduce((sum, cell) => sum + cell.recordCount, 0);

  function chooseSpecies(speciesId: string) {
    const next = new URLSearchParams(searchParams);
    next.set("species", speciesId);
    setSearchParams(next);
    setSelectedCellId(null);
  }

  return (
    <main id="main">
      <span className="eyebrow">Distribution</span>
      <h1 className="page-title" tabIndex={-1}>Explore the map</h1>
      <p className="page-lead">
        Choose a species to see where it has been recorded, as grid squares at the
        resolution the records support. Select a point on the map to ask what has been
        recorded near it.
      </p>

      <Caveat />

      <div className="explore-layout">
        <div className="map-col">
          {speciesState.status === "error" ? (
            <div className="directory-state">
              <ErrorState message={speciesState.error.message} onRetry={() => void speciesQuery.refetch()} />
            </div>
          ) : cellsState.status === "empty" ? (
            <div className="directory-state">
              <EmptyState message={`No mapped records for ${activeName || "this species"} yet.`} />
            </div>
          ) : activeId ? (
            <ErrorBoundary label="the map">
              <Suspense fallback={<div className="map-card" style={{ display: "grid", placeItems: "center" }}><LoadingState label="the map" /></div>}>
                <DistributionMap
                  key={activeId}
                  speciesId={activeId}
                  selectedCellId={selectedCellId}
                  onSelectCell={setSelectedCellId}
                  radius={centre ? { centre, metres: radiusMetres } : null}
                  onPickCentre={setCentre}
                />
              </Suspense>
            </ErrorBoundary>
          ) : (
            <div className="state"><LoadingState label="the map" /></div>
          )}
        </div>

        <div className="side-panel">
          <section className="panel" aria-labelledby="explore-species-heading">
            <div className="panel-body">
              <h2 id="explore-species-heading" style={{ fontSize: "1.05rem", marginBottom: ".5rem" }}>
                Species
              </h2>
              {speciesState.status === "loading" ? (
                <LoadingState label="species" />
              ) : (
                <div className="splist" role="group" aria-label="Choose a species">
                  {options.map((item) => {
                    const name = item.commonName ?? item.scientificName;
                    return (
                      <button
                        key={item.speciesId}
                        type="button"
                        aria-pressed={item.speciesId === activeId}
                        onClick={() => chooseSpecies(item.speciesId)}
                      >
                        <span>{name}</span>
                        {item.commonName ? <span className="sci">{item.scientificName}</span> : null}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </section>

          <section className="panel" aria-labelledby="explore-nearby-heading">
            <div className="panel-body">
              <h2 id="explore-nearby-heading" style={{ fontSize: "1.05rem", marginBottom: ".4rem" }}>
                Recorded near a point
              </h2>

              <div className="control-field" style={{ marginBottom: ".7rem" }}>
                <label htmlFor="explore-radius">Search radius</label>
                <select
                  id="explore-radius"
                  value={String(radiusMetres)}
                  onChange={(event) => setRadiusMetres(Number(event.target.value))}
                >
                  {RADII.map((metres) => (
                    <option key={metres} value={metres}>{formatDistance(metres)}</option>
                  ))}
                </select>
              </div>

              {centre === null ? (
                <p className="state" style={{ padding: 0 }}>
                  Select a point on the map to see which grid squares fall within the
                  chosen distance of it.
                </p>
              ) : (
                <div aria-live="polite">
                  <p className="results-summary">
                    <strong>{formatNumber(nearby.length)}</strong>{" "}
                    {nearby.length === 1 ? "square" : "squares"} within{" "}
                    {formatDistance(radiusMetres)}, holding{" "}
                    <strong>{formatNumber(nearbyRecords)}</strong>{" "}
                    {nearbyRecords === 1 ? "record" : "records"} of {activeName}.
                  </p>

                  {coarserThanQuery ? (
                    <p className="unavailable" style={{ marginTop: ".6rem", fontSize: ".84rem" }}>
                      <strong>The answer is coarser than the question.</strong> These records
                      are published as{" "}
                      {describeResolution(Math.max(...nearby.map((c) => c.precisionMetres)))}s,
                      so a {formatDistance(radiusMetres)} radius cannot narrow them further —
                      any square it touches is returned whole.
                    </p>
                  ) : null}

                  {nearby.length === 0 ? (
                    <p className="state" style={{ padding: ".4rem 0 0" }}>
                      Nothing recorded within this distance. That means no records here — not
                      that the species is absent.
                    </p>
                  ) : (
                    <ul style={{ listStyle: "none", padding: 0, margin: ".6rem 0 0" }}>
                      {nearby.slice(0, 12).map((cell) => (
                        <li key={cell.cellId} style={{ padding: ".3rem 0", borderTop: "1px solid var(--line)" }}>
                          <button
                            type="button"
                            className="cell-select"
                            aria-pressed={cell.cellId === selectedCellId}
                            onClick={() => setSelectedCellId(cell.cellId)}
                            style={{ justifyContent: "flex-start", width: "100%" }}
                          >
                            <strong>{cell.cellId}</strong>
                            <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: ".5rem" }}>
                              {formatNumber(cell.recordCount)} records ·{" "}
                              {cell.distanceMetres === 0
                                ? "contains the point"
                                : `${formatDistance(cell.distanceMetres)} away`}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}

                  {nearby.length > 12 ? (
                    <p className="map-note">
                      Showing the 12 nearest of {formatNumber(nearby.length)}.{" "}
                      <Link href={`/records?species=${encodeURIComponent(activeId)}`}>
                        See every square as a table →
                      </Link>
                    </p>
                  ) : null}

                  <button
                    type="button"
                    className="btn-ghost"
                    style={{ marginTop: ".7rem" }}
                    onClick={() => setCentre(null)}
                  >
                    Clear the search area
                  </button>
                </div>
              )}
            </div>
          </section>

          {active ? (
            <p className="map-note">
              <Link href={`/species/${encodeURIComponent(active.speciesId)}/${active.slug}`}>
                Full page for {activeName} →
              </Link>
            </p>
          ) : null}
        </div>
      </div>
    </main>
  );
}
