import { toAsyncState, useRecords } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";

// The mandatory R5 non-map fallback: everything the map conveys, in an accessible table.
// Shows gridRef at its stated precision only — no precise coords, no Comments, no PII.
export function RecordsTable() {
  const query = useRecords();
  const state = toAsyncState(query, (d) => d.items.length === 0);
  if (state.status === "loading") return <LoadingState label="records" />;
  if (state.status === "error") return <ErrorState message={state.error.message} onRetry={() => void query.refetch()} />;
  if (state.status === "empty") return <EmptyState />;
  return (
    <section aria-labelledby="records-heading">
      <h2 id="records-heading">Records (accessible table)</h2>
      <table>
        <caption>Species records shown at their true grid resolution.</caption>
        <thead>
          <tr>
            <th scope="col">Species</th>
            <th scope="col">Grid reference</th>
            <th scope="col">Resolution</th>
            <th scope="col">Year</th>
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
              <td>{r.year}</td>
              <td>{r.recordType ?? "—"}</td>
              <td>{r.verified}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
