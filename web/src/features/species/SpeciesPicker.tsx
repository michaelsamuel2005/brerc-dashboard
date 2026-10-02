import { useState } from "react";
import { ErrorState, LoadingState } from "../../components/states/States";
import { toAsyncState, useSpeciesList } from "../../lib/api";
import { useDebouncedValue } from "../../lib/hooks/useDebouncedValue";

/** How many matches to offer at once. A list, not the catalogue. */
const RESULT_LIMIT = 20;

interface Props {
  /** The species currently in view, or null before anything is chosen. */
  selectedId: string | null;
  onSelect: (speciesId: string) => void;
  /** Distinguishes the input ids when two pickers share a page. */
  idPrefix: string;
  label?: string;
}

function displayName(species: { commonName: string | null; scientificName: string }): string {
  return species.commonName ?? species.scientificName;
}

/**
 * Choose a species by searching for it.
 *
 * This replaces a `<select>`, and the reason is a number: BRERC hold roughly
 * **15,000–16,000 species** (client meeting 2). A dropdown populated with the first
 * hundred is not a smaller version of the right control — it is a control that silently
 * answers a different question, offering 0.6% of the catalogue while looking complete.
 * They raised the same point themselves: "with this many species — plants and insects
 * especially — the list can be very large and scrolling takes time".
 *
 * So the search runs on the server through the existing `?q=` parameter, and the count
 * of matches is always stated. If a species is not in the list, the visitor is told how
 * many matched, not left to assume the list is everything.
 */
export function SpeciesPicker({ selectedId, onSelect, idPrefix, label = "Species" }: Props) {
  const [draft, setDraft] = useState("");
  const query = useDebouncedValue(draft.trim());

  const listQuery = useSpeciesList({
    ...(query ? { q: query } : {}),
    sort: "name-asc",
    page: 1,
    pageSize: RESULT_LIMIT,
  });
  const state = toAsyncState(listQuery, (data) => data.items.length === 0);
  const total = listQuery.data?.total ?? 0;
  const shown = listQuery.data?.items.length ?? 0;

  return (
    <div className="species-picker">
      <div className="control-field">
        <label htmlFor={`${idPrefix}-species-search`}>{label}</label>
        <input
          id={`${idPrefix}-species-search`}
          type="search"
          placeholder="Search by common or scientific name…"
          autoComplete="off"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </div>

      {/* One live region for the whole control. Screen readers announce how many
          matched, which is the fact a dropdown of 100 was hiding. */}
      <p className="result-count" aria-live="polite">
        {state.status === "loading"
          ? "Searching species"
          : state.status === "error"
            ? "Species could not be loaded"
            : total === 0
              ? `No species match “${query}”`
              : shown < total
                ? `${shown} of ${total.toLocaleString("en-GB")} matching species — keep typing to narrow`
                : `${total.toLocaleString("en-GB")} ${total === 1 ? "species" : "species"}`}
      </p>

      {state.status === "error" ? (
        <ErrorState message={state.error.message} onRetry={() => void listQuery.refetch()} />
      ) : state.status === "loading" ? (
        <LoadingState label="species" />
      ) : state.status === "empty" ? null : (
        <div className="splist" role="group" aria-label="Choose a species">
          {state.data.items.map((species) => (
            <button
              key={species.speciesId}
              type="button"
              aria-pressed={species.speciesId === selectedId}
              onClick={() => onSelect(species.speciesId)}
            >
              <span>{displayName(species)}</span>
              {species.commonName ? <span className="sci">{species.scientificName}</span> : null}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
