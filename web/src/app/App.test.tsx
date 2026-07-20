import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

// A dedicated test QueryClient: no retries, no cache carry-over, so the test is
// deterministic and doesn't hang on retry back-off regardless of machine speed.
function renderApp(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("App (integration, against MSW mock)", () => {
  it(
    "renders live data from the mock and has no accessibility violations",
    async () => {
      const { container } = renderApp(<App />);
      // Data flows from the mock API. Generous timeout for a cold first run.
      expect(await screen.findByText(/Slow-worm/, undefined, { timeout: 8000 })).toBeInTheDocument();
      // Records table (the R5 non-map fallback) renders the same source.
      expect(await screen.findByRole("table")).toBeInTheDocument();
      const results = await axe(container);
      expect(results).toHaveNoViolations();
    },
    15000,
  );
});
