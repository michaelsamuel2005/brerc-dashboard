import { useEffect, useRef } from "react";
import { toAsyncState, useDistributionCells } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";
import { usePrefersReducedMotion } from "../../lib/hooks/usePrefersReducedMotion";

interface Props {
  speciesId: string;
  selectedCellId?: string | null;
  onSelectCell?: (cellId: string | null) => void;
}

// The map's ACCESSIBLE EQUIVALENT (R5) AND its keyboard control surface (R2): the SAME
// CellCollection the map draws, as a table. Each row's grid-square button highlights that
// square on the map; the selected row is highlighted and scrolled into view. Scoped to
// one species.
export function CellSummaryTable({ speciesId, selectedCellId = null, onSelectCell }: Props) {
  const query = useDistributionCells({ species: speciesId });
  const state = toAsyncState(query, (d) => d.features.length === 0);
  const reduced = usePrefersReducedMotion();
  const selectedRowRef = useRef<HTMLTableRowElement | null>(null);

  // Bring the selected row into view when selection changes (e.g. chosen on the map).
  useEffect(() => {
    if (selectedCellId && selectedRowRef.current) {
      selectedRowRef.current.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
    }
  }, [selectedCellId, reduced]);

  const total = state.status === "ready" ? state.data.features.reduce((n, f) => n + f.properties.recordCount, 0) : 0;

  return (
    <section className="table-section" aria-labelledby="cells-heading">
      <h2 id="cells-heading">Distribution by grid square</h2>
      <p className="map-note">
        The same information the map shows above, as a table — one row per grid square
        {state.status === "ready" ? ` (${state.data.features.length} squares, ${total.toLocaleString("en-GB")} records)` : ""}.
        Select a square to highlight it on the map.
      </p>
      {state.status === "loading" ? (
        <div className="state"><LoadingState label="the distribution" /></div>
      ) : state.status === "error" ? (
        <ErrorState message={state.error.message} onRetry={() => void query.refetch()} />
      ) : state.status === "empty" ? (
        <EmptyState message="No mapped records for this species yet." />
      ) : (
        <div className="tablewrap">
          <div className="tscroll" tabIndex={0} role="group" aria-label="Distribution by grid square, scrollable">
            <table className="data">
              <caption>Every grid square shown on the map, with its record counts. Squares are 1 km; no exact locations.</caption>
              <thead>
                <tr>
                  <th scope="col">Grid square</th>
                  <th scope="col">Resolution</th>
                  <th scope="col" className="num">Records</th>
                  <th scope="col" className="num">Verified</th>
                </tr>
              </thead>
              <tbody>
                {state.data.features.map((f) => {
                  const sel = f.properties.cellId === selectedCellId;
                  return (
                    <tr key={f.properties.cellId} ref={sel ? selectedRowRef : undefined} className={sel ? "selected" : undefined}>
                      <td>
                        <button
                          type="button"
                          className="cell-select"
                          aria-pressed={sel}
                          onClick={() => onSelectCell?.(sel ? null : f.properties.cellId)}
                        >
                          {f.properties.cellId}
                          <span className="visually-hidden"> — {sel ? "highlighted on the map; activate to clear" : "highlight on the map"}</span>
                        </button>
                      </td>
                      <td>{precisionLabel(f.properties.precisionMetres)}</td>
                      <td className="num">{f.properties.recordCount.toLocaleString("en-GB")}</td>
                      <td className="num">{f.properties.verifiedCount?.toLocaleString("en-GB") ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
