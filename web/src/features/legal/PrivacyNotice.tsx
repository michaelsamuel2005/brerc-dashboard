import { Link } from "wouter";

/**
 * Privacy notice.
 *
 * Written from an audit of what the built app actually does, not from a template: there
 * are no analytics, no tag manager, no cookies and no `document.cookie` anywhere in the
 * source, the fonts are self-hosted, and the only third party a visitor's browser
 * contacts is the basemap tile CDN. That last one is a real disclosure, and it is stated
 * here plainly rather than buried, because it is the only case where an IP address
 * leaves our control.
 */
function Outstanding({ children }: { children: React.ReactNode }) {
  return (
    <mark style={{ background: "var(--accent-bg)", color: "var(--accent-d)", padding: "0 .25rem", borderRadius: "4px" }}>
      [BRERC to confirm: {children}]
    </mark>
  );
}

export function PrivacyNotice() {
  return (
    <main id="main">
      <span className="eyebrow">Statement</span>
      <h1 className="page-title" tabIndex={-1}>Privacy</h1>
      <p className="page-lead">
        What this site does and does not do with information about you. The short version:
        there is no account, no tracking and no cookie, and the only thing that leaves your
        browser is the request for the background map.
      </p>

      <div className="unavailable" style={{ marginBottom: "var(--sp-3)" }} role="note">
        <strong>Draft — not yet published.</strong> The technical facts below are audited
        against the built application. The highlighted items are for BRERC and Bristol City
        Council's data protection officer to complete before this goes live.
      </div>

      <div className="prose">
        <h2>No account, no cookies, no analytics</h2>
        <p>
          You do not sign in, and we do not ask for anything about you. The site sets{" "}
          <strong>no cookies</strong>. There is no analytics package, no tag manager and no
          advertising or social-media script of any kind — which is why you were not shown a
          cookie banner: there is nothing to consent to.
        </p>

        <h2>Settings stored on your device</h2>
        <p>
          If you choose a colour theme or row density on the{" "}
          <Link href="/settings">settings page</Link>, that choice is saved in your browser's
          local storage so the site looks the same next time. It stays on your device, is
          never transmitted, and cannot identify you. Clearing your browser's site data
          removes it.
        </p>

        <h2>The background map</h2>
        <p>
          The map's background imagery is fetched from <strong>CARTO</strong>, using data from
          OpenStreetMap contributors. To send you those images, CARTO necessarily receives
          your IP address and the areas of the map you are looking at. This is the only
          third-party request the site makes.
        </p>
        <p>
          The data layer — the grid squares, their counts, and everything in the tables —
          comes from BRERC's own server, not from CARTO. If you block the tile provider, the
          squares and every figure still work; you simply lose the streets underneath.
        </p>
        <p>
          CARTO's own handling of that data is governed by its privacy policy, and BRERC's
          position on relying on it is <Outstanding>whether to continue with a third-party tile provider or self-host the basemap</Outstanding>.
        </p>

        <h2>Fonts and other assets</h2>
        <p>
          Every other asset — fonts, styles, scripts, images — is served from this site's own
          address. The typefaces are licensed under the SIL Open Font License and hosted here
          rather than loaded from a font CDN, specifically so that no third party is told
          which pages you visit.
        </p>

        <h2>Server logs</h2>
        <p>
          The web server keeps standard request logs, which include IP addresses, for security
          and troubleshooting. Retention and the lawful basis are{" "}
          <Outstanding>log retention period and lawful basis under UK GDPR</Outstanding>.
        </p>

        <h2>Wildlife records and personal data</h2>
        <p>
          The records shown here have had personal data removed before publication. Recorder
          names and any other identifying fields are not sent to your browser and are not
          present in the published data at all.
        </p>
        {/* The single sentence below is the one place location generalisation is still
            mentioned anywhere on the site. BRERC asked at client meeting 2 for the
            explanation of how it works to be removed, and it has been removed everywhere
            else — this says only THAT it happens, with no method, no tiers and no
            indication of which species. A privacy notice silent on processing that does
            occur is a weaker document, so this is our recommendation, not a decision;
            Tim can strike it. */}
        <p>
          Locations of protected species are generalised before publication. See{" "}
          <Link href="/about">about the data</Link> for what each square means.
        </p>

        <h2>Your rights and who to contact</h2>
        <p>
          The data controller for this site is <Outstanding>the data controller and its registration</Outstanding>,
          and the data protection officer can be reached at{" "}
          <Outstanding>data protection officer contact details</Outstanding>. You have the
          right to complain to the{" "}
          <a href="https://ico.org.uk/make-a-complaint/">Information Commissioner's Office</a>.
        </p>
      </div>
    </main>
  );
}
