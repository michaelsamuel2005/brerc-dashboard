// The effort-bias + honesty caveat that accompanies every distribution view.
export function Caveat() {
  return (
    <aside className="caveat" aria-label="How to read this data">
      <strong>How to read this.</strong> Records show <em>where wildlife has been recorded</em> and reflect recording
      activity, not complete distribution or abundance. Locations are shown at their public capture resolution — a
      larger square represents a broader capture area, not an exact-location pin.
    </aside>
  );
}
