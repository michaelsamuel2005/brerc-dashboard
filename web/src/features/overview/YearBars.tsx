interface Props {
  data: readonly { year: number; count: number }[];
  /** Sentence describing the whole chart, for anyone who cannot see it. */
  label: string;
}

const HEIGHT = 160;
const GAP_RATIO = 0.25;

/**
 * The recording-effort chart on the overview.
 *
 * Hand-drawn SVG rather than Recharts on purpose: this is the landing page, and pulling
 * in a 370 kB charting library to draw plain rectangles would be the single largest
 * asset on the first page a visitor sees. It also lets the bars take their fill from a
 * CSS token, so the chart follows the theme.
 *
 * Accessibility: the drawing is one `role="img"` with a summarising label — individual
 * bars are NOT focusable, because a bar 4 pixels wide cannot be a 44px touch target.
 * The equivalent table beside it is the accessible interface, exactly as on the species
 * page. Nothing here is conveyed by colour alone: every bar's value is in that table.
 */
export function YearBars({ data, label }: Props) {
  if (data.length === 0) return null;
  const max = Math.max(...data.map((d) => d.count));
  const step = 100 / data.length;
  const width = step * (1 - GAP_RATIO);

  return (
    <svg
      className="year-bars"
      viewBox={`0 0 100 ${HEIGHT}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      {data.map((d, index) => {
        // Guard against a zero max: a release with every count at 0 would otherwise
        // divide by zero and render NaN into the DOM.
        const height = max > 0 ? (d.count / max) * (HEIGHT - 4) : 0;
        return (
          <rect
            key={d.year}
            className="bar-default"
            x={index * step + (step - width) / 2}
            y={HEIGHT - height}
            width={width}
            height={height}
          />
        );
      })}
    </svg>
  );
}
