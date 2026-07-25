import { toAsyncState, useRecords } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";

// The mandatory R5 non-map fallback: everything the map conveys, in an accessible table.
// Shows each grid reference at its stated precision only — no precise coordinates, no
// Comments, no recorder names. This is the equal-access path to the map's data.
export function RecordsTable() {
  const query = useRecords();
  const state = toAsyncState(query, (d) => d.items.length === 0);

  return (
    <section className="table-section" aria-labelledby="records-heading">
      <h2 id="records-heading">Records — accessible table</h2>
      <p className="map-note">
        The same data the map shows, as a table. Nothing here is available only by using the map.
      </p>
      {state.status === "loading" ? (
        <div className="state"><LoadingState label="records" /></div>
      ) : state.status === "error" ? (
        <ErrorState message={state.error.message} onRetry={() => void query.refetch()} />
      ) : state.status === "empty" ? (
        <EmptyState message="No records to list." />
      ) : (
        <div className="tablewrap">
          <div className="tscroll">
            <table className="data">
              <caption>Species records, shown at their true grid resolution — no precise coordinates or personal data.</caption>
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
