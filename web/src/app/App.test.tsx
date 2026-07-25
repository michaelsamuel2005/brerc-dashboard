import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";

// The distribution map needs WebGL, which jsdom lacks, so we stub the lazy-loaded map
// module. The accessible records table is the a11y + data target here; the map's visual
// render is verified in a real browser (see the P2 run notes).
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
    "renders the species and the accessible records table with no accessibility violations",
    async () => {
      const { container } = renderApp(<App />);
      // Species panel + records table both resolve from the mock API.
      expect(await screen.findByText(/Slow-worm/, undefined, { timeout: 8000 })).toBeInTheDocument();
      expect(await screen.findByRole("table")).toBeInTheDocument();
      const results = await axe(container);
      expect(results).toHaveNoViolations();
    },
    15000,
  );
});
