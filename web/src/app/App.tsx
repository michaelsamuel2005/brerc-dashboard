import { SkipLink } from "../components/SkipLink";
import { ErrorBoundary } from "./ErrorBoundary";
import { SummaryBanner } from "../features/landing/SummaryBanner";
import { SpeciesList } from "../features/species/SpeciesList";
import { RecordsTable } from "../features/species/RecordsTable";

export function App() {
  return (
    <>
      <SkipLink />
      <header>
        <h1>BRERC — Species Records Explorer</h1>
      </header>
      <main id="main">
        <ErrorBoundary label="the overview">
          <SummaryBanner />
        </ErrorBoundary>
        <ErrorBoundary label="the species list">
          <SpeciesList />
        </ErrorBoundary>
        <ErrorBoundary label="the records table">
          <RecordsTable />
        </ErrorBoundary>
      </main>
      <footer>
        <p>Data © BRERC. Records reflect recording effort, not true distribution.</p>
      </footer>
    </>
  );
}
