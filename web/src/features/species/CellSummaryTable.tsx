import { toAsyncState, useDistributionCells } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";

interface Props {
  speciesId: string;
  selectedCellId?: string | null;
  onSelectCell?: (cellId: string | null) => void;
}

// The map's ACCESSIBLE EQUIVALENT (R5) AND its keyboard control surface (R2): the SAME
// cells the map draws, as a table. Each row's grid-square button highlights that square on
// the map (and updates the selected-cell card); the selected row is visually marked. No
// auto-scroll — the persistent card carries the readout, so selecting never moves the page.
export function CellSummaryTable({ speciesId, selectedCellId = null, onSelectCell }: Props) {
  const query = useDistributionCells({ species: speciesId });
  const state = toAsyncState(query, (d) => d.cells.length === 0);
  const total = state.status === "ready" ? state.data.cells.reduce((n, c) => n + c.recordCount, 0) : 0;

  return (
    <section className="table-section" aria-labelledby="cells-heading">
      <h2 id="cells-heading">Distribution by grid square</h2>
      <p className="map-note">
        The same information the map shows above, as a table — one row per grid square
        {state.status === "ready" ? ` (${state.data.cells.length} squares, ${total.toLocaleString("en-GB")} records)` : ""}.
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
                {state.data.cells.map((c) => {
                  const sel = c.cellId === selectedCellId;
                  return (
                    <tr key={c.cellId} className={sel ? "selected" : undefined}>
                      <td>
                        <button
                          type="button"
                          className="cell-select"
                          aria-pressed={sel}
                          onClick={() => onSelectCell?.(sel ? null : c.cellId)}
                        >
                          {c.cellId}
                          <span className="visually-hidden"> — {sel ? "highlighted on the map; activate to clear" : "highlight on the map"}</span>
                        </button>
                      </td>
                      <td>{precisionLabel(c.precisionMetres)}</td>
                      <td className="num">{c.recordCount.toLocaleString("en-GB")}</td>
                      <td className="num">{c.verifiedCount?.toLocaleString("en-GB") ?? "—"}</td>
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
