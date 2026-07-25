import { toAsyncState, useDistributionCells } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";

// The map's ACCESSIBLE EQUIVALENT (R5): the SAME CellCollection the map draws, rendered
// as a table — grid square, resolution, record count, verified count. Keyboard and
// screen-reader users obtain exactly what map users see. Scoped to one species.
export function CellSummaryTable({ speciesId }: { speciesId: string }) {
  const query = useDistributionCells({ species: speciesId });
  const state = toAsyncState(query, (d) => d.features.length === 0);

  const total = state.status === "ready" ? state.data.features.reduce((n, f) => n + f.properties.recordCount, 0) : 0;

  return (
    <section className="table-section" aria-labelledby="cells-heading">
      <h2 id="cells-heading">Distribution by grid square</h2>
      <p className="map-note">
        The same information the map shows above, as a table — one row per grid square
        {state.status === "ready" ? ` (${state.data.features.length} squares, ${total.toLocaleString("en-GB")} records)` : ""}.
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
                {state.data.features.map((f) => (
                  <tr key={f.properties.cellId}>
                    <td>{f.properties.cellId}</td>
                    <td>{precisionLabel(f.properties.precisionMetres)}</td>
                    <td className="num">{f.properties.recordCount.toLocaleString("en-GB")}</td>
                    <td className="num">{f.properties.verifiedCount?.toLocaleString("en-GB") ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
