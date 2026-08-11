// The effort-bias + honesty caveat that accompanies every distribution view.
export function Caveat() {
  return (
    <aside className="caveat" aria-label="How to read this data">
      <strong>How to read this.</strong> Records show <em>where people looked</em>, not true distribution or
      abundance. The locations of sensitive species are generalised to protect them, and every cell is drawn at its
      true precision — a larger square means a coarser record, never a false-precision pin.
    </aside>
  );
}
