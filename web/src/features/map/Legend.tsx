import { useState } from "react";
import { LEGEND_BANDS } from "./mapConfig";

// Colour-safe legend: every band carries a text label, so meaning never depends on
// colour alone (WCAG 1.4.1). Readable by sighted and screen-reader users alike.
export function Legend() {
  const [expanded, setExpanded] = useState(false);

  return (
    <section className="legend" aria-label="Map key">
      <button
        type="button"
        className="legend-summary"
        aria-expanded={expanded}
        aria-controls="map-key-content"
        onClick={() => setExpanded((current) => !current)}
      >
        Map key
      </button>
      <div className="legend-content" id="map-key-content" hidden={!expanded}>
        <span className="legend-subtitle">Records in each displayed grid square</span>
        {LEGEND_BANDS.map((band) => (
          <div className="legend-row" key={band.label}>
            <span className="legend-sw" style={{ background: band.colour }} aria-hidden="true" />
            {band.label}
          </div>
        ))}
        <span className="legend-note">Darker blue means more records. The squares are translucent so the map remains visible.</span>
      </div>
    </section>
  );
}
