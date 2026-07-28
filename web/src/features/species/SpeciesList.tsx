import { toAsyncState, useSpeciesList } from "../../lib/api";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";

export function SpeciesList() {
  const query = useSpeciesList();
  const state = toAsyncState(query, (d) => d.items.length === 0);
  if (state.status === "loading") return <LoadingState label="species" />;
  if (state.status === "error") return <ErrorState message={state.error.message} onRetry={() => void query.refetch()} />;
  if (state.status === "empty") return <EmptyState message="No species match your filters." />;
  return (
    <section aria-labelledby="species-heading">
      <h2 id="species-heading">Species</h2>
      <ul>
        {state.data.items.map((sp) => (
          <li key={sp.speciesId}>
            <strong>{sp.commonName ?? sp.scientificName}</strong> <em>({sp.scientificName})</em> —{" "}
            {sp.recordCount.toLocaleString()} records
          </li>
        ))}
      </ul>
    </section>
  );
}
