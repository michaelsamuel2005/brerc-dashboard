import { Link } from "wouter";

/**
 * About the data.
 *
 * The three panels carry the copy written for the mid-review prototype, because it is
 * the clearest statement anyone on the project has made of what a biological record
 * does and does not mean. This page is the honest counterweight to a map: a map invites
 * you to read absence as evidence, and this is where we say plainly that it is not.
 */
export function AboutPage() {
  return (
    <main id="main">
      <span className="eyebrow">How to read it honestly</span>
      <h1 className="page-title" tabIndex={-1}>About the data</h1>
      <p className="page-lead">
        Biological records are a picture of effort as much as of nature. Here is how this
        dashboard presents them honestly and safely.
      </p>

      <div className="notes">
        <section className="note" aria-labelledby="about-effort">
          <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <path d="M3 12h4l3 8 4-16 3 8h4" />
          </svg>
          <h2 id="about-effort">Effort, not a census</h2>
          <p>
            A filled square means people looked and recorded there — not that a species is
            absent everywhere else. Records reflect where recorders go, which is shaped by
            access, habit and the surveys that happened to be funded.
          </p>
        </section>

        <section className="note" aria-labelledby="about-sensitive">
          <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z" />
            <path d="M9 12l2 2 4-4" />
          </svg>
          <h2 id="about-sensitive">Sensitive places protected</h2>
          <p>
            The locations of vulnerable species are generalised to a coarse grid{" "}
            <em>before</em> they ever reach this site. The public map only ever receives
            already-safe squares, and carries no marker of which species were treated this
            way — a marker would itself point at what it is meant to hide.
          </p>
        </section>

        <section className="note" aria-labelledby="about-resolution">
          <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M3 9h18M8 4v16" />
          </svg>
          <h2 id="about-resolution">Honest resolution</h2>
          <p>
            Squares are drawn at the true precision of the record — a large square where the
            location is coarse, and never a pin, which would claim a precision the record
            does not have. Each square states its own capture resolution.
          </p>
        </section>
      </div>

      <div className="prose">
        <h2>Why squares and not points</h2>
        <p>
          A point on a map has a centre, and a centre reads as "the animal was here". Almost
          no biological record supports that claim: most are captured to a grid square, and
          records of protected species are deliberately coarsened further. Drawing a square
          says exactly what is known — <em>somewhere in this area</em> — and nothing more.
        </p>
        <p>
          This is why the map does not offer a "precise location" view at any zoom level.
          There is no hidden precise layer to reveal; the data reaching this site has already
          been generalised, in the database, before it was published.
        </p>

        <h2>What a record is</h2>
        <p>
          Someone saw a species, noted where and when, and submitted it. BRERC verifies what
          it can and holds the result. A record is evidence of a sighting — not of a
          population, a territory, or continued presence.
        </p>
        <ul>
          <li><strong>An empty square</strong> may mean nobody has surveyed it.</li>
          <li><strong>A dense square</strong> may mean a well-watched nature reserve, or one very active recorder.</li>
          <li><strong>An old record</strong> means the species was there then. It does not mean it is there now, or that it has gone.</li>
        </ul>

        <h2>What is not published here</h2>
        <p>
          Recorder names and any other personal data are removed before publication; they are
          never sent to your browser. Neither are precise coordinates, grid references finer
          than the published capture resolution, or the raw source fields.
        </p>

        <h2>Accessibility and privacy</h2>
        <p>
          Every map on this site has a table beside it carrying the same information, because
          a map is not usable by everyone. See the{" "}
          <Link href="/accessibility">accessibility statement</Link> for what we have tested
          and what is still outstanding, and the <Link href="/privacy">privacy notice</Link>{" "}
          for what leaves your browser.
        </p>
      </div>
    </main>
  );
}
