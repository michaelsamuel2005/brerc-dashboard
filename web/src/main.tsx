import React from "react";
import ReactDOM from "react-dom/client";
import { Router } from "wouter";
import { useHashLocation } from "wouter/use-hash-location";
import { App } from "./app/App";
import { shouldEnableMocking } from "./app/mocking";
import { Providers } from "./app/providers";
import { applyStoredPreferences } from "./app/theme";
// Self-hosted (OFL-1.1), served from our own origin. Loading this from Google would
// send every visitor's IP address to a third party and is blocked by our own CSP.
// Weight-axis variable file only: ~48 kB, and one face for the whole site since BRERC
// asked for the serif to go (client meeting 2).
import "@fontsource-variable/inter/wght.css";
import "./styles/tokens.css";
import "./styles/views.css";

// Before React renders, so the first paint of the app is already in the right theme
// rather than flashing the default and correcting itself.
applyStoredPreferences();

// By default the whole UI runs against the MSW mock (A11) in dev — no backend
// needed. `VITE_USE_REAL_API=1` points dev at a locally-running API instead;
// see docs/RUN_LOCALLY.md. A production build never mocks.
async function enableMocking(): Promise<void> {
  // DO NOT MERGE THESE TWO GUARDS, AND DO NOT REORDER THEM.
  //
  // This first line must stay a literal `import.meta.env.DEV` test. Vite
  // substitutes `false` for it in a production build, which makes everything
  // below unreachable, so Rollup drops the dynamic import and MSW is never
  // emitted at all. Replacing it with a function call defeats that constant
  // fold and ships a ~300 kB mock chunk to the public — measured, not assumed.
  // `scripts/guard-bundle.mjs` fails the build if that ever happens again.
  if (!import.meta.env.DEV) return;
  // The rule itself, unit-tested in ./app/mocking. It repeats the production
  // check deliberately: the line above is a bundler optimisation, this is the
  // behavioural guarantee, and neither should depend on the other holding.
  if (!shouldEnableMocking(import.meta.env)) return;

  const { worker } = await import("./test/msw/browser");
  await worker.start({ onUnhandledRequest: "bypass" });
}

void enableMocking().then(() => {
  const rootEl = document.getElementById("root");
  if (!rootEl) throw new Error("Root element #root not found");
  ReactDOM.createRoot(rootEl).render(
    <React.StrictMode>
      <Providers>
        <Router hook={useHashLocation}>
          <App />
        </Router>
      </Providers>
    </React.StrictMode>,
  );
});
