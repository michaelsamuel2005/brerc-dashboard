import { Route, Routes } from "react-router-dom";
import { SkipLink } from "../components/SkipLink";
import { ErrorBoundary } from "./ErrorBoundary";
import { SpeciesList } from "../features/species/SpeciesList";
import { SpeciesDetailPage } from "../features/species/SpeciesDetailPage";


export function App() {
  return (
    <>
      <SkipLink />
      <header className="app-header">
        <div className="row">
          <span className="brand">
            BRERC <span className="tag">Prototype</span>
          </span>
          <span className="sub">Wildlife of the West of England</span>
        </div>
      </header>

      <main id="main">
        <Routes>
          <Route
            path="/"
            element={
              <>
                <ErrorBoundary label="the species list">
                  <SpeciesList />
                </ErrorBoundary>
              </>
            }
          />
          <Route path="/species/:speciesId" element={<SpeciesDetailPage />} />
        </Routes>
      </main>

      <footer className="app-footer">
        <div className="row">
          Data © BRERC · illustrative demo data · records reflect recording effort, not true distribution.
        </div>
      </footer>
    </>
  );
}
