import { useEffect } from "react";
import {
  Link,
  Redirect,
  Route,
  Switch,
  useLocation,
  useParams,
} from "wouter";
import { SkipLink } from "../components/SkipLink";
import { SpeciesList } from "../features/species/SpeciesList";
import { SpeciesDashboard } from "./SpeciesDashboard";

const DEFAULT_SPECIES_PATH = "/species/DEMO-001/anguis-fragilis";

function SpeciesRoute() {
  const { speciesId } = useParams<{ speciesId: string; slug: string }>();
  if (!speciesId) return <Redirect to="/species" replace />;
  return <SpeciesDashboard key={speciesId} speciesId={speciesId} />;
}

function PrimaryNavigation() {
  const [pathname] = useLocation();
  return (
    <nav className="app-nav" aria-label="Primary">
      <Link href="/species" aria-current={pathname === "/species" ? "page" : undefined}>
        Species
      </Link>
    </nav>
  );
}

function NotFound() {
  return (
    <main id="main" className="directory-page">
      <span className="eyebrow">Not found</span>
      <h1 className="page-title" tabIndex={-1}>That page does not exist</h1>
      <p className="page-lead">Choose a species from the directory to continue.</p>
      <Link className="btn" href="/species">Browse species</Link>
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
  return (
    <>
      <SkipLink />
      <header className="app-header">
        <div className="row">
          <Link className="brand" href={DEFAULT_SPECIES_PATH} aria-label="BRERC prototype home">
            BRERC <span className="tag">Prototype</span>
          </Link>
          <PrimaryNavigation />
          <span className="sub">Wildlife of the West of England</span>
        </div>
      </header>

      <RouteFocus />
      <Switch>
        <Route path="/"><Redirect to={DEFAULT_SPECIES_PATH} replace /></Route>
        <Route path="/species"><SpeciesList /></Route>
        <Route path="/species/:speciesId/:slug"><SpeciesRoute /></Route>
        <Route><NotFound /></Route>
      </Switch>

      <footer className="app-footer">
        <div className="row">
          Data © BRERC · illustrative demo data · records reflect recording effort, not true distribution.
        </div>
      </footer>
    </>
  );
}
