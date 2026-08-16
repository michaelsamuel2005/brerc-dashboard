import { Suspense, lazy, useEffect, useState } from "react";
import { Link, Route, Switch, useLocation, useParams } from "wouter";
import { SkipLink } from "../components/SkipLink";
import { LoadingState } from "../components/states/States";
import { AboutPage } from "../features/about/AboutPage";
import { AccessibilityStatement } from "../features/legal/AccessibilityStatement";
import { PrivacyNotice } from "../features/legal/PrivacyNotice";
import { OverviewPage } from "../features/overview/OverviewPage";
import { RecordsPage } from "../features/records/RecordsPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { SpeciesList } from "../features/species/SpeciesList";
import { NavDrawer } from "./NavDrawer";
import { SpeciesDashboard } from "./SpeciesDashboard";
import { currentNavHref, FOOTER_ITEMS, NAV_ITEMS } from "./navigation";
import { nextTheme, setTheme, storedTheme } from "./theme";

// Both pull in maplibre-gl (~800 kB). Nobody browsing the species directory or reading
// the accessibility statement should pay for it.
const ExplorePage = lazy(() => import("../features/explore/ExplorePage"));

function SpeciesRoute() {
  const { speciesId } = useParams<{ speciesId: string; slug: string }>();
  if (!speciesId) return <SpeciesList />;
  return <SpeciesDashboard key={speciesId} speciesId={speciesId} />;
}

function PrimaryNavigation({ pathname }: { pathname: string }) {
  const current = currentNavHref(pathname);
  return (
    <nav className="app-nav" aria-label="Primary">
      {NAV_ITEMS.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={current === item.href ? "page" : undefined}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

function ThemeToggle() {
  // Held in state only so the pressed label stays truthful after a click; the source of
  // truth is the stored preference, applied to <html> before React ever rendered.
  const [theme, setLocalTheme] = useState(() => storedTheme());

  function toggle() {
    const systemPrefersDark =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = nextTheme(theme, systemPrefersDark);
    setTheme(next);
    setLocalTheme(next);
  }

  return (
    <button
      type="button"
      className="iconbtn"
      onClick={toggle}
      // The icon alone would be meaningless to a screen reader, and "toggle theme"
      // would not say what happens. Name the destination.
      aria-label={theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme"}
      title={theme === "dark" ? "Light theme" : "Dark theme"}
    >
      <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
    </button>
  );
}

function NotFound() {
  return (
    <main id="main" className="directory-page">
      <span className="eyebrow">Not found</span>
      <h1 className="page-title" tabIndex={-1}>That page does not exist</h1>
      <p className="page-lead">
        The address may be mistyped, or the page may have moved. Start from the overview
        or browse the species directory.
      </p>
      <p>
        <Link className="btn" href="/">Go to the overview</Link>
      </p>
    </main>
  );
}

/** Focus the new page heading after client-side navigation, just as a full page load would. */
function RouteFocus() {
  const [pathname] = useLocation();

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const heading = document.querySelector<HTMLElement>("#main h1");
      heading?.focus({ preventScroll: true });
      document.title = heading ? `${heading.textContent ?? "BRERC"} | BRERC` : "BRERC";
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
    }, 0);
    return () => window.clearTimeout(timer);
  }, [pathname]);

  return null;
}

export function App() {
  const [pathname] = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  // A route change must close the drawer, or a link tap leaves the overlay covering the
  // page it just navigated to.
  useEffect(() => setMenuOpen(false), [pathname]);

  return (
    <>
      <SkipLink />
      <header className="app-header">
        <div className="row">
          <Link className="brand" href="/" aria-label="BRERC prototype home">
            BRERC <span className="tag">Prototype</span>
          </Link>
          <PrimaryNavigation pathname={pathname} />
          <div className="header-tools">
            <ThemeToggle />
            <button
              type="button"
              className="iconbtn menubtn"
              aria-expanded={menuOpen}
              aria-label="Open menu"
              onClick={() => setMenuOpen(true)}
            >
              <span aria-hidden="true">☰</span>
            </button>
          </div>
        </div>
      </header>

      {menuOpen ? (
        <NavDrawer
          items={[...NAV_ITEMS, ...FOOTER_ITEMS]}
          pathname={pathname}
          onClose={() => setMenuOpen(false)}
        />
      ) : null}

      <RouteFocus />
      <Switch>
        <Route path="/"><OverviewPage /></Route>
        <Route path="/explore">
          <Suspense fallback={<main id="main"><h1 className="page-title" tabIndex={-1}>Explore the map</h1><div className="state"><LoadingState label="the map" /></div></main>}>
            <ExplorePage />
          </Suspense>
        </Route>
        <Route path="/species"><SpeciesList /></Route>
        <Route path="/species/:speciesId/:slug"><SpeciesRoute /></Route>
        <Route path="/records"><RecordsPage /></Route>
        <Route path="/about"><AboutPage /></Route>
        <Route path="/accessibility"><AccessibilityStatement /></Route>
        <Route path="/privacy"><PrivacyNotice /></Route>
        <Route path="/settings"><SettingsPage /></Route>
        <Route><NotFound /></Route>
      </Switch>

      <footer className="app-footer">
        <div className="row">
          <p style={{ margin: "0 0 .5rem" }}>
            Data © BRERC · illustrative demo data · records reflect recording effort, not true distribution.
          </p>
          <nav aria-label="Site information" style={{ display: "flex", flexWrap: "wrap", gap: ".2rem 1rem" }}>
            {FOOTER_ITEMS.map((item) => (
              <Link key={item.href} href={item.href}>{item.label}</Link>
            ))}
          </nav>
        </div>
      </footer>
    </>
  );
}
