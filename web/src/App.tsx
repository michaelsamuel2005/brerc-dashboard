import { SkipLink } from './components/SkipLink';
import { SummaryBar } from './components/SummaryBar';
import { SpeciesSearch } from './components/SpeciesSearch';
import { FiltersPanel } from './components/Filters';
import { SpeciesInfoPanel } from './components/SpeciesInfoPanel';
import { MapView } from './components/MapView';
import { DataTable } from './components/DataTable';

// This is the SKELETON layout. As you build each component (Learning Guide
// Modules 5-6), replace its placeholder and wire the real state here: a `filters`
// object (species, taxon group, year range) and a `selected` species, passed down
// as props. Answer Key: brerc-public-dashboard/web/src/App.tsx
export function App() {
  return (
    <>
      <SkipLink />
      <header className="app-header">
        <h1>BRERC species-distribution dashboard</h1>
        <p>Foundation skeleton — build the pieces one by one (see BUILD_PLAN.md).</p>
      </header>
      <SummaryBar />
      <div className="layout">
        <aside className="sidebar" aria-label="Search, filters and species information">
          <SpeciesSearch />
          <FiltersPanel />
          <SpeciesInfoPanel />
        </aside>
        <main id="main-content" className="content" tabIndex={-1}>
          <MapView />
          <DataTable />
        </main>
      </div>
    </>
  );
}
