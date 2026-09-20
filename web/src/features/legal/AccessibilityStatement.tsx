import { Link } from "wouter";

/**
 * Accessibility statement, on the gov.uk model.
 *
 * Publishing one is a legal obligation under the Public Sector Bodies (Websites and
 * Mobile Applications) (No. 2) Accessibility Regulations 2018, and the regulations
 * require it to be ACCURATE — a statement claiming compliance the site does not have is
 * itself a breach. So this says what has actually been tested, and lists what has not.
 *
 * Deployment- and owner-specific facts cannot be invented by a developer. They are
 * marked with <Outstanding>, and the page carries a draft banner until the frozen
 * deployed build has completed manual review and BRERC has approved the placeholders,
 * compliance status and wording.
 */
function Outstanding({ children }: { children: React.ReactNode }) {
  return (
    <mark style={{ background: "var(--accent-bg)", color: "var(--accent-d)", padding: "0 .25rem", borderRadius: "4px" }}>
      [BRERC to confirm: {children}]
    </mark>
  );
}

export function AccessibilityStatement() {
  return (
    <main id="main">
      <span className="eyebrow">Statement</span>
      <h1 className="page-title" tabIndex={-1}>Accessibility statement</h1>

      <div className="unavailable" style={{ marginBottom: "var(--sp-3)" }} role="note">
        <strong>Draft — not approved for production publication.</strong> The structure is
        prepared, but final testing of the exact deployed build, named manual reviews and
        BRERC approval are still outstanding. Highlighted items are facts only BRERC can
        supply. This draft must not be treated as the final accessibility statement.
      </div>

      <div className="prose">
        <p className="updated">
          This statement applies to the BRERC species distribution dashboard. It was
          prepared on <Outstanding>date of preparation</Outstanding> and last reviewed on{" "}
          <Outstanding>date of last review</Outstanding>.
        </p>

        <h2>Using this website</h2>
        <p>
          This dashboard is being developed for the Bristol Regional Environmental Records
          Centre. It is designed so that people can:
        </p>
        <ul>
          <li>navigate the whole site, including the map, using a keyboard alone;</li>
          <li>zoom to 400% without content being lost or requiring horizontal scrolling;</li>
          <li>read every figure the map shows in a table instead of the map;</li>
          <li>use it with a screen reader, including the map's data;</li>
          <li>change the colour theme and row spacing to suit you.</li>
        </ul>
        <p>
          These capabilities remain subject to final manual verification on the deployed
          service.
        </p>
        <p>
          <a href="https://mcmw.abilitynet.org.uk/">AbilityNet</a> has advice on making your
          device easier to use if you have a disability.
        </p>

        <h3>Typography</h3>
        <p>
          The site is set in Inter, a typeface designed for screen reading, with clearly
          distinguished letterforms — a capital I, a lower-case l and the digit 1 do not
          look alike — and figures of even width so numbers line up in the data tables.
        </p>
        <p>
          It is served from this website rather than a font service, so no third party is
          told which pages you visit. All text sizes are set in relative units, so the
          site follows the text size set in your browser or operating system. The final
          review will verify usability at 200% text resize and 400% browser zoom on the
          exact deployed build.
        </p>

        <h2>How accessible this website is</h2>
        <p>
          The final compliance status against the{" "}
          <a href="https://www.w3.org/TR/WCAG22/">Web Content Accessibility Guidelines version 2.2</a>{" "}
          AA standard has not yet been approved. Automated candidate checks have passed,
          but the manual and assistive-technology review of the exact deployed build is
          outstanding. The current known limitation and provisionally out-of-scope content
          are listed below; this list is not final until that review is complete.
        </p>

        <h3>Non-accessible content</h3>
        <h4>Non-compliance with the accessibility regulations</h4>
        <ul>
          <li>
            <strong>The map itself cannot be operated by a screen reader as a map.</strong> It
            is a graphical rendering of grid squares. The design provides a table containing
            each displayed square's aggregate count and capture resolution, and browser
            automation checks keyboard synchronisation between map and table. Whether this
            is an effective screen-reader equivalent remains to be confirmed in the final
            manual review. A person who needs the spatial relationships themselves does not
            get them from the table.
          </li>
          <li>
            <strong>No independent accessibility audit has been carried out.</strong> The
            findings currently available come from project-team automated candidate testing.
            The named manual review and any independent audit are still outstanding. An
            external audit is <Outstanding>whether an external audit is planned, and when</Outstanding>.
          </li>
        </ul>

        <h4>Content that is not within the scope of the regulations</h4>
        <ul>
          <li>
            <strong>Third-party background map.</strong> The final provider, privacy
            arrangement and legal scope must be confirmed for the deployed service.
            Automated candidate tests exercise tile failure and keep the aggregate data table
            available; manual verification on the deployed build and BRERC approval of this
            classification are pending.
          </li>
        </ul>

        <h2>What we have tested, and how</h2>
        <p>
          Automated regression testing runs on repository changes. The results below are
          candidate evidence only; the final statement must be tied to one frozen deployed
          build and completed manual-review record.
        </p>
        <ul>
          <li>
            <strong>Colour contrast has automated regression checks.</strong> Defined text
            and interface colour pairs in the light and dark themes are checked against the
            1.4.3 and 1.4.11 thresholds. Representative map-layer combinations are checked
            separately. Actual rendered and composited states still require the recorded
            manual contrast sweep.
          </li>
          <li>
            <strong>Automated checks</strong> using axe-core and project-specific rules run
            against controlled routes, states and viewports in Chromium, Firefox and WebKit.
            They supplement, but do not replace, human evaluation.
          </li>
          <li>
            <strong>Keyboard regression checks</strong> cover critical map, table and
            navigation interactions. A named reviewer must still verify the complete focus
            order, visible focus and task usability on the deployed build.
          </li>
          <li>
            <strong>Touch-target geometry</strong> is checked automatically in controlled
            states. Physical iOS and Android touch testing, including accidental activation
            and pointer cancellation, remains part of the final manual round.
          </li>
        </ul>
        <p>
          Automated tools cannot determine accessibility on their own. The required manual
          screen-reader, keyboard/focus, resize, zoom, contrast, physical-touch,
          pointer-cancellation, status-announcement and orientation reviews are{" "}
          <Outstanding>the outcome of the completed manual accessibility round</Outstanding>.
        </p>

        <h2>Feedback and contact information</h2>
        <p>
          If you need information on this website in a different format, or you find a problem
          not listed on this page, contact us at <Outstanding>contact email address and postal address</Outstanding>.
          We will consider your request and get back to you within{" "}
          <Outstanding>response time commitment</Outstanding>.
        </p>

        <h2>Enforcement procedure</h2>
        <p>
          The Equality and Human Rights Commission is responsible for enforcing the Public
          Sector Bodies (Websites and Mobile Applications) (No. 2) Accessibility Regulations
          2018. If you are not happy with how we respond to your complaint, contact the{" "}
          <a href="https://www.equalityadvisoryservice.com/">Equality Advisory and Support Service</a>.
        </p>

        <h2>Preparation of this statement</h2>
        <p>
          This draft was prepared by the project team building the dashboard. It currently
          reflects automated candidate testing with synthetic scenarios. Before publication,
          it must be updated from testing of the frozen deployed build, the completed manual
          evidence and BRERC's approved hosting and contact details. It must be reviewed again
          whenever a change alters the evidence or scope described above.
        </p>
        <p>
          See also the <Link href="/privacy">privacy notice</Link> and{" "}
          <Link href="/about">about the data</Link>.
        </p>
      </div>
    </main>
  );
}
