import { Link } from "wouter";

/**
 * About the data.
 *
 * What changed after client meeting 2, and why:
 *
 * BRERC asked for "the explanation of how sensitive species locations are blurred" to be
 * removed — their reasoning being that there is no need for people to know how it is
 * done, and the public will use the given resolution anyway. So this page no longer
 * describes the mechanism: no tiers, no coarse grid, no "before it reaches this site",
 * and no panel drawing attention to which species get that treatment. Naming the method
 * also tells a reader which squares to be interested in, which is the opposite of the
 * point.
 *
 * What stays is what a square MEANS — an area, at a stated capture resolution, not a
 * place. Removing that too would leave the map claiming a precision it does not have,
 * which is not what BRERC asked for and is the one thing this page exists to prevent.
 *
 * "Capture resolution" throughout: BRERC's own term for it.
 */
export function AboutPage() {
  return (
    <main id="main">
      <span className="eyebrow">How to read it honestly</span>
      <h1 className="page-title" tabIndex={-1}>About the data</h1>
      <p className="page-lead">
        Wildlife records show where people have looked as much as where wildlife is. Here
        is how to read what this map is telling you.
      </p>

      <div className="notes">
        <section className="note" aria-labelledby="about-effort">
          <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <path d="M3 12h4l3 8 4-16 3 8h4" />
          </svg>
          <h2 id="about-effort">Where people looked</h2>
          <p>
            A shaded square means somebody went there and recorded what they saw. An empty
            square usually means nobody has been, not that there is nothing to find.
          </p>
        </section>

        <section className="note" aria-labelledby="about-square">
          <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M3 9h18M8 4v16" />
          </svg>
          <h2 id="about-square">An area, not a spot</h2>
          <p>
            Each square covers an area, and every square says how big it is — its{" "}
            <strong>capture resolution</strong>. A record sits somewhere inside its square.
            The map never shows a pin, because a pin would say &ldquo;here&rdquo;, and
            that is more than the record knows.
          </p>
        </section>

        <section className="note" aria-labelledby="about-time">
          <svg className="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
          <h2 id="about-time">A record is one sighting</h2>
          <p>
            Somebody saw a species, wrote down where and when, and sent it in. It is
            evidence that the species was there then. It does not say how many there were,
            or whether they are still there now.
          </p>
        </section>
      </div>

      <div className="prose">
        <h2>Reading the map</h2>
        <ul>
          <li>
            <strong>An empty square</strong> usually means nobody has surveyed it.
          </li>
          <li>
            <strong>A dark square</strong> may be a nature reserve people visit often, or
            one very busy recorder — not necessarily more wildlife.
          </li>
          <li>
            <strong>An old record</strong> means the species was there then. It has not
            been checked since.
          </li>
          <li>
            <strong>A bigger square</strong> means the location was noted less precisely.
            It is not a bigger population.
          </li>
        </ul>

        <h2>Counting records</h2>
        <p>
          The charts count records by the year they were <em>recorded</em>, not the year
          BRERC received them. If a batch of older records is added to the database this
          month, it raises the earlier year it belongs to, not this one.
        </p>
        <p>
          Squares are listed in grid order rather than ranked by how many records they
          hold. A ranking would be a table of where people record, and it is easily
          misread as a table of where wildlife is.
        </p>

        <h2>What is not shown</h2>
        <p>
          Recorder names and other personal details are not published and are never sent
          to your browser. Neither are locations more precise than the capture resolution
          shown on each square.
        </p>

        <h2>Accessibility and privacy</h2>
        <p>
          Every map here has a table beside it with the same information, because a map is
          not usable by everyone. See the{" "}
          <Link href="/accessibility">accessibility statement</Link> for what has been
          tested, and the <Link href="/privacy">privacy notice</Link> for what leaves your
          browser.
        </p>
      </div>
    </main>
  );
}
