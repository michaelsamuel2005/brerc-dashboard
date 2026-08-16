import { Suspense, lazy, useEffect, useRef, useState } from "react";
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

/**
 * Move focus to the new page heading after CLIENT-SIDE navigation, the way a full page
 * load would — but never on the first render.
 *
 * On a cold load the browser already has focus at the top of the document, which is what
 * makes the skip link reachable with the very first Tab (WCAG 2.4.1 Bypass Blocks).
 * Stealing focus into the `<h1>` there sends that first Tab *past* the skip link, so the
 * one control that exists to let a keyboard user skip the navigation becomes the one
 * control they cannot reach. The title is still set, because that costs nothing.
 *
 * This was live and unnoticed: the browser test that guards the skip link passed only
 * because `/` used to redirect, and the extra render happened to delay this effect past
 * the test's keypress. Changing the landing route removed the delay and the defect
 * surfaced. It was always a defect — the redirect was hiding it, not preventing it.
 */
function RouteFocus() {
  const [pathname] = useLocation();
  // The path this component last MOVED FOCUS for, seeded with the one it mounted on.
  //
  // Not a boolean "first render" flag: React StrictMode deliberately runs every effect
  // twice in development, so a flag flipped on the first pass is already false on the
  // second and the focus move happens anyway. Comparing the path is immune to that —
  // a re-run with an unchanged path is not a navigation, whatever caused it.
  const focusedPath = useRef(pathname);

  useEffect(() => {
    const heading = document.querySelector<HTMLElement>("#main h1");
    document.title = heading ? `${heading.textContent ?? "BRERC"} | BRERC` : "BRERC";

    if (focusedPath.current === pathname) return;
    focusedPath.current = pathname;

    const timer = window.setTimeout(() => {
      const target = document.querySelector<HTMLElement>("#main h1");
      target?.focus({ preventScroll: true });
      document.title = target ? `${target.textContent ?? "BRERC"} | BRERC` : "BRERC";
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
