import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";

// The distribution map needs WebGL, which jsdom lacks, so we stub the lazy-loaded map
// module. The two accessible tables are the a11y + data target here; the map's visual
// render and keyboard behaviour are verified in a real browser (Playwright, pending).
vi.mock("../features/map/DistributionMap", () => ({
  default: function DistributionMapStub() {
    return null;
  },
}));

function renderApp(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("App — P2 slice (integration, against MSW mock)", () => {
  it(
    "renders the scoped species and BOTH the cell-summary and sample tables with no accessibility violations",
    async () => {
      const { container } = renderApp(<App />);
      expect(await screen.findByText(/Slow-worm/, undefined, { timeout: 8000 })).toBeInTheDocument();
      // the map's accessible equivalent + the individual-records sample
      expect(await screen.findByText(/Distribution by grid square/)).toBeInTheDocument();
      expect(await screen.findByText(/Sample of individual records/)).toBeInTheDocument();
      const tables = await screen.findAllByRole("table");
      expect(tables.length).toBeGreaterThanOrEqual(2);
      const results = await axe(container);
      expect(results).toHaveNoViolations();
    },
    20000,
  );
});
