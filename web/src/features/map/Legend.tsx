import { LEGEND_BANDS } from "./mapConfig";

// Colour-safe legend: every band carries a text label, so meaning never depends on
// colour alone (WCAG 1.4.1). Readable by sighted and screen-reader users alike.
export function Legend() {
  return (
    <div className="legend">
      <b>Records per 1&nbsp;km square</b>
      {LEGEND_BANDS.map((band) => (
        <div className="legend-row" key={band.label}>
          <span className="legend-sw" style={{ background: band.colour }} aria-hidden="true" />
          {band.label}
        </div>
      ))}
    </div>
  );
}
