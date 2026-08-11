import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toAsyncState, useSpeciesList } from "../../lib/api";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";

const DEFAULT_PAGE_SIZE = 20;

function yearSpan(sp: { firstYear: number | null; lastYear: number | null }): string | null {
  if (sp.firstYear === null || sp.lastYear === null) return null;
  return sp.firstYear === sp.lastYear ? `${sp.firstYear}` : `${sp.firstYear}–${sp.lastYear}`;
}

// Species index (R3): a browsable, paginated list of species. Each row is a real link
// (never a div with onClick) so it is reachable and openable by keyboard, and navigates
// to /species/:speciesId — a real URL, not just client-side selection state. Pagination
// is server-side: page/pageSize are sent as query params and `total` drives page count.
export function SpeciesList({ pageSize = DEFAULT_PAGE_SIZE }: { pageSize?: number } = {}) {
  const [page, setPage] = useState(1);
  // Pagination happens server-side: the hook's query key includes page/pageSize, so
  // each page is its own cached request and `total` (not items.length) is the source
  // of truth for how many pages exist.
  const query = useSpeciesList({ page, pageSize });
  const state = toAsyncState(query, (d) => d.items.length === 0);

  // A live region announces the result count only when it CHANGES after mount (see
  // States.tsx) — a region that already has text on first render is never announced.
  const total = state.status === "ready" ? state.data.total : null;
  const [announced, setAnnounced] = useState("");
  useEffect(() => {
    if (total !== null) setAnnounced(`Showing ${total.toLocaleString()} species`);
  }, [total]);

  if (state.status === "loading") return <LoadingState label="species" />;
  if (state.status === "error") return <ErrorState message={state.error.message} onRetry={() => void query.refetch()} />;
  if (state.status === "empty") return <EmptyState message="No species match your filters." />;

  const { items, total: totalItems } = state.data;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const currentPage = Math.min(page, totalPages);

  return (
    <section aria-labelledby="species-heading">
      <h2 id="species-heading">Species</h2>
      <p role="status" aria-live="polite" className="visually-hidden">
        {announced}
      </p>
      <ul className="species-index">
        {items.map((sp) => {
          const span = yearSpan(sp);
          return (
            <li key={sp.speciesId}>
              <Link className="btn species-index-link" to={`/species/${sp.speciesId}`}>
                <strong>{sp.commonName ?? sp.scientificName}</strong> <em>({sp.scientificName})</em> — {sp.group} —{" "}
                {sp.recordCount.toLocaleString()} records{span ? ` — ${span}` : ""}
              </Link>
            </li>
          );
        })}
      </ul>
      <nav aria-label="Species list pagination" className="species-index-pagination">
        <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={currentPage <= 1}>
          Previous
        </button>
        <span>
          Page {currentPage} of {totalPages}
        </span>
        <button
          type="button"
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          disabled={currentPage >= totalPages}
        >
          Next
        </button>
      </nav>
    </section>
  );
}
