import { useDistributionCells } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";

// The single, stable readout of the selected cell — beside the map. Derived from ONE
// authoritative selectedCellId (shared with map + table). Identical DOM structure whether
// or not a cell is selected (values become "—"), so selecting never changes the card's
// height and cannot reflow the page. Stable "Selected square" heading (correct outline);
// aria-live announces the change.
export function SelectedCellCard({
  speciesId,
  year = null,
  selectedCellId,
  onClear,
}: {
  speciesId: string;
  year?: number | null;
  selectedCellId: string | null;
  onClear: () => void;
}) {
  const query = useDistributionCells({ species: speciesId, year: year ?? undefined });
  const cell = selectedCellId ? query.data?.cells.find((c) => c.cellId === selectedCellId) ?? null : null;
  const verificationAvailable = query.data?.verificationAvailable;
  const verifiedPct =
    verificationAvailable && cell && cell.verifiedCount !== undefined && cell.recordCount > 0
      ? Math.round((cell.verifiedCount / cell.recordCount) * 100)
      : null;

  return (
    <div className={cell ? "cell-card" : "cell-card cell-card--empty"} aria-live="polite">
      <div className="cell-card__head">
        <h2>Selected square</h2>
        <button
          type="button"
          className="btn-ghost"
          onClick={onClear}
          disabled={!cell}
          style={{ visibility: cell ? "visible" : "hidden" }}
        >
          Clear selection
        </button>
      </div>
      <p className="cell-card__id">{cell ? cell.cellId : "None selected"}</p>
      <dl className="cell-card__stats">
        <div>
          <dt>Capture resolution</dt>
          <dd>{cell ? precisionLabel(cell.precisionMetres) : "—"}</dd>
        </div>
        <div>
          <dt>Records</dt>
          <dd>{cell ? cell.recordCount.toLocaleString("en-GB") : "—"}</dd>
        </div>
        <div>
          <dt>{cell && verificationAvailable === false ? "Verification unavailable" : "Verified"}</dt>
          <dd>
            {cell
              ? verificationAvailable === false
                ? "Not available"
                : `${cell.verifiedCount?.toLocaleString("en-GB") ?? "—"}${verifiedPct !== null ? ` (${verifiedPct}%)` : ""}`
              : "—"}
          </dd>
        </div>
      </dl>
    </div>
  );
}
