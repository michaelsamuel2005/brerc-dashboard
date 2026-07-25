import { useDistributionCells } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";

// The single, stable readout of the selected cell — beside the map. Derived from ONE
// authoritative selectedCellId (shared with the map + table), so nothing can disagree.
// aria-live announces the selection to screen-reader users. No auto-scroll, no popup.
export function SelectedCellCard({
  speciesId,
  selectedCellId,
  onClear,
}: {
  speciesId: string;
  selectedCellId: string | null;
  onClear: () => void;
}) {
  const query = useDistributionCells({ species: speciesId });
  const cell = query.data?.cells.find((c) => c.cellId === selectedCellId) ?? null;

  if (!selectedCellId || !cell) {
    return (
      <div className="cell-card cell-card--empty" aria-live="polite">
        Select a grid square — on the map or in the table below — to see its details here.
      </div>
    );
  }

  const verifiedPct =
    cell.recordCount > 0 && cell.verifiedCount !== undefined ? Math.round((cell.verifiedCount / cell.recordCount) * 100) : null;

  return (
    <div className="cell-card" aria-live="polite">
      <div className="cell-card__head">
        <h3>{cell.cellId}</h3>
        <button type="button" className="btn-ghost" onClick={onClear}>
          Clear selection
        </button>
      </div>
      <dl className="cell-card__stats">
        <div>
          <dt>Resolution</dt>
          <dd>{precisionLabel(cell.precisionMetres)}</dd>
        </div>
        <div>
          <dt>Records</dt>
          <dd>{cell.recordCount.toLocaleString("en-GB")}</dd>
        </div>
        <div>
          <dt>Verified</dt>
          <dd>
            {cell.verifiedCount?.toLocaleString("en-GB") ?? "—"}
            {verifiedPct !== null ? ` (${verifiedPct}%)` : ""}
          </dd>
        </div>
      </dl>
    </div>
  );
}
