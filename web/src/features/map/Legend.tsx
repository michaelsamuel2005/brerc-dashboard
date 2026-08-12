import { LEGEND_BANDS } from "./mapConfig";

// Colour-safe legend: every band carries a text label, so meaning never depends on
// colour alone (WCAG 1.4.1). Readable by sighted and screen-reader users alike.
export function Legend() {
  return (
    <section className="legend" aria-labelledby="map-key-title">
      <strong className="legend-title" id="map-key-title">Map key</strong>
      <span className="legend-subtitle">Records in each displayed grid square</span>
      {LEGEND_BANDS.map((band) => (
        <div className="legend-row" key={band.label}>
          <span className="legend-sw" style={{ background: band.colour }} aria-hidden="true" />
          {band.label}
        </div>
      ))}
      <span className="legend-note">Darker green means more records.</span>
    </section>
  );
}
