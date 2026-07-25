import { toAsyncState, useRecords } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";

// A SAMPLE of individual records for ONE species — NOT the map's equivalent (that is the
// grid-square table above). Grid references show at their true resolution, never finer
// than the 100 m public floor; no coordinates, no personal data.
export function RecordsTable({ speciesId }: { speciesId: string }) {
  const query = useRecords({ species: speciesId });
  const state = toAsyncState(query, (d) => d.items.length === 0);

  return (
    <section className="table-section" aria-labelledby="records-heading">
      <h2 id="records-heading">Sample of individual records</h2>
      <p className="map-note">
        {state.status === "ready"
          ? `A sample of ${state.data.items.length} of ${state.data.total.toLocaleString("en-GB")} records for this species.`
          : "Individual records behind the distribution shown above."}
      </p>
      {state.status === "loading" ? (
        <div className="state"><LoadingState label="records" /></div>
      ) : state.status === "error" ? (
        <ErrorState message={state.error.message} onRetry={() => void query.refetch()} />
      ) : state.status === "empty" ? (
        <EmptyState message="No records to list for this species." />
      ) : (
        <div className="tablewrap">
          <div className="tscroll" tabIndex={0} role="group" aria-label="Sample of individual records, scrollable">
            <table className="data">
              <caption>Individual records at their true grid resolution (100 m or coarser) — no exact coordinates or personal data.</caption>
              <thead>
                <tr>
                  <th scope="col">Species</th>
                  <th scope="col">Grid reference</th>
                  <th scope="col">Resolution</th>
                  <th scope="col" className="num">Year</th>
                  <th scope="col">Record type</th>
                  <th scope="col">Verified</th>
                </tr>
              </thead>
              <tbody>
                {state.data.items.map((r) => (
                  <tr key={r.id}>
                    <td>{r.commonName ?? r.scientificName}</td>
                    <td>{r.gridRef}</td>
                    <td>{precisionLabel(r.precisionMetres)}</td>
                    <td className="num">{r.year}</td>
                    <td>{r.recordType ?? "—"}</td>
                    <td style={{ textTransform: "capitalize" }}>{r.verified}</td>
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
