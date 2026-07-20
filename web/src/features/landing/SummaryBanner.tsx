import { toAsyncState, useSummary } from "../../lib/api";
import { ErrorState, LoadingState } from "../../components/states/States";

export function SummaryBanner() {
  const state = toAsyncState(useSummary());
  if (state.status === "loading") return <LoadingState label="summary" />;
  if (state.status === "error") return <ErrorState message={state.error.message} />;
  if (state.status === "empty") return null;
  const s = state.data;
  return (
    <section aria-labelledby="summary-heading">
      <h2 id="summary-heading">Overview</h2>
      <p>
        {s.totalRecords.toLocaleString()} records across {s.totalSpecies.toLocaleString()} species,{" "}
        {s.yearRange.min}&ndash;{s.yearRange.max}.
      </p>
      <p>
        <strong>Please note:</strong> {s.coverageCaveat}
      </p>
    </section>
  );
}
