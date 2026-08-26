// The effort-bias + honesty caveat that accompanies every distribution view.
export function Caveat() {
  return (
    <aside className="caveat" aria-label="How to read this data">
      <strong>How to read this.</strong> Records show <em>where wildlife has been recorded</em>, which reflects where
      people have looked — not how much wildlife is there. Each square states its <strong>capture resolution</strong>:
      the record is somewhere inside that square, and a larger square means a broader area, never a bigger population.
    </aside>
  );
}
