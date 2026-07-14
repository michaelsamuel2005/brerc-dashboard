import type { CSSProperties } from 'react';
import { Routes, Route, Link } from 'react-router-dom';

/**
 * App shell + routing. This component assumes a Router is provided by its parent
 * (BrowserRouter in main.tsx, MemoryRouter in tests) — it must NOT include its own
 * Router, so it stays testable in isolation.
 *
 * P0 is a minimal, accessible shell: a skip link, one <h1> per page, real landmarks
 * and keyboard-operable navigation. Feature routes (map, species, search, about) are
 * filled in over the following phases.
 */
export function App() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>

      <header style={headerStyle}>
        <Link to="/" style={{ fontWeight: 700, textDecoration: 'none' }}>
          🌿 BRERC — West of England wildlife records
        </Link>
      </header>

      <main id="main" tabIndex={-1} style={mainStyle}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/map" element={<Placeholder title="Species distribution map" />} />
          <Route path="/species" element={<Placeholder title="Browse species" />} />
          <Route path="*" element={<Placeholder title="Page not found" />} />
        </Routes>
      </main>

      <footer style={footerStyle}>
        <p>Records held by BRERC · A 180 Degrees Consulting Bristol project.</p>
      </footer>
    </>
  );
}

function LandingPage() {
  return (
    <section aria-labelledby="landing-heading">
      <h1 id="landing-heading">Explore wildlife records for the West of England</h1>
      <p>
        Discover what species have been recorded near you across Bristol, Bath &amp; North East
        Somerset, North Somerset and South Gloucestershire.
      </p>
      <p>
        <strong>These are records, not a population count.</strong> An empty area may simply mean no
        one has looked there yet — not that nothing lives there.
      </p>
      <nav aria-label="Explore">
        <ul>
          <li>
            <Link to="/map">Explore the distribution map</Link>
          </li>
          <li>
            <Link to="/species">Browse species</Link>
          </li>
        </ul>
      </nav>
    </section>
  );
}

function Placeholder({ title }: { title: string }) {
  return (
    <section aria-labelledby="ph-heading">
      <h1 id="ph-heading">{title}</h1>
      <p>This part of the dashboard is coming soon.</p>
      <p>
        <Link to="/">Back to the start</Link>
      </p>
    </section>
  );
}

const headerStyle: CSSProperties = {
  maxWidth: 'var(--content-max)',
  margin: '0 auto',
  padding: 'var(--space-4)',
  borderBottom: '1px solid var(--color-border)',
};
const mainStyle: CSSProperties = {
  maxWidth: 'var(--content-max)',
  margin: '0 auto',
  padding: 'var(--space-4)',
};
const footerStyle: CSSProperties = {
  maxWidth: 'var(--content-max)',
  margin: '0 auto',
  padding: 'var(--space-4)',
  color: 'var(--color-text-muted)',
  borderTop: '1px solid var(--color-border)',
};
