import { Link } from "wouter";

/**
 * Accessibility statement, on the gov.uk model.
 *
 * Publishing one is a legal obligation under the Public Sector Bodies (Websites and
 * Mobile Applications) (No. 2) Accessibility Regulations 2018, and the regulations
 * require it to be ACCURATE — a statement claiming compliance the site does not have is
 * itself a breach. So this says what has actually been tested, and lists what has not.
 *
 * Three facts cannot be invented by a developer: BRERC's contact route, the date of the
 * last review, and the enforcement wording BRERC's own legal team signs off. They are
 * marked with <Outstanding> and the page carries a draft banner until they are supplied,
 * so it cannot be published half-finished by accident.
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
        <strong>Draft — not yet published.</strong> The structure and the technical findings
        below are complete and accurate. The highlighted items are facts only BRERC can
        supply; the statement should not go live until they are filled in and BRERC has
        approved the wording.
      </div>

      <div className="prose">
        <p className="updated">
          This statement applies to the BRERC species distribution dashboard. It was
          prepared on <Outstanding>date of preparation</Outstanding> and last reviewed on{" "}
          <Outstanding>date of last review</Outstanding>.
        </p>

        <h2>Using this website</h2>
        <p>This website is run by the Bristol Regional Environmental Records Centre. We want as many people as possible to be able to use it. That means you should be able to:</p>
        <ul>
          <li>navigate the whole site, including the map, using a keyboard alone;</li>
          <li>zoom to 400% without content being lost or requiring horizontal scrolling;</li>
          <li>read every figure the map shows in a table instead of the map;</li>
          <li>use it with a screen reader, including the map's data;</li>
          <li>change the colour theme and row spacing to suit you.</li>
        </ul>
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
          site follows the text size set in your browser or operating system, and remains
          usable when text is enlarged to 200% and when the page is zoomed to 400%.
        </p>

        <h2>How accessible this website is</h2>
        <p>
          We believe this website is <strong>partially compliant</strong> with the{" "}
          <a href="https://www.w3.org/TR/WCAG22/">Web Content Accessibility Guidelines version 2.2</a>{" "}
          AA standard. The non-compliances and exemptions are listed below.
        </p>

        <h3>Non-accessible content</h3>
        <h4>Non-compliance with the accessibility regulations</h4>
        <ul>
          <li>
            <strong>The map itself cannot be operated by a screen reader as a map.</strong> It
            is a graphical rendering of grid squares. Every square it draws, with its record
            count and its capture resolution, is published in the table directly beneath it,
            and that table is fully keyboard- and screen-reader-operable;
            selecting a row highlights the square and vice versa. We consider the table the
            accessible equivalent, but a user who wants the spatial relationships themselves
            does not get them.
          </li>
          <li>
            <strong>No independent accessibility audit has been carried out.</strong> The
            findings here come from our own automated and manual testing, described below.
            An external audit is <Outstanding>whether an external audit is planned, and when</Outstanding>.
          </li>
        </ul>

        <h4>Content that is not within the scope of the regulations</h4>
        <ul>
          <li>
            <strong>Third-party map tiles.</strong> The background map imagery is supplied by
            OpenStreetMap contributors via CARTO. We do not control its rendering, and it
            carries no information required to understand the data — the grid squares and
            their table do. The map remains usable, and the data layer remains readable, if
            the background imagery fails to load.
          </li>
        </ul>

        <h2>What we have tested, and how</h2>
        <p>Testing is automated and runs on every change, so this statement describes the current build rather than a snapshot:</p>
        <ul>
          <li>
            <strong>Colour contrast is measured, not eyeballed.</strong> Every text and
            interface colour pair in both the light and dark themes is checked against the
            1.4.3 and 1.4.11 thresholds by a test that reads the stylesheet itself. The map's
            square colours and their outlines are measured against the background imagery
            they are drawn over.
          </li>
          <li>
            <strong>Automated checks</strong> using axe-core run against every page in a real
            browser, at desktop and mobile widths.
          </li>
          <li>
            <strong>Keyboard operation</strong> of the map, the tables and the navigation is
            asserted by browser tests, including that a map click never scrolls the page and
            that the menu returns focus to the button that opened it.
          </li>
          <li>
            <strong>Touch targets</strong> are 44 × 44 pixels or larger throughout.
          </li>
        </ul>
        <p>
          Automated tools catch a minority of accessibility problems. Manual testing with
          assistive technology is described in our mobile and screen-reader test protocol,
          and its results are <Outstanding>the outcome of the manual assistive-technology testing round</Outstanding>.
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
          This statement was prepared by the project team building the dashboard. It is based
          on our own testing of the live build, not on a self-assessment questionnaire, and it
          is reviewed whenever a change alters what is listed above.
        </p>
        <p>
          See also the <Link href="/privacy">privacy notice</Link> and{" "}
          <Link href="/about">about the data</Link>.
        </p>
      </div>
    </main>
  );
}
