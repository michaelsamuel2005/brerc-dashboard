import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import type { ReactNode } from "react";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { DEFAULT_SPECIES_ID, DEFAULT_SPECIES_SLUG } from "../test/fixtures";

// The distribution map needs WebGL, which jsdom lacks, so we stub the lazy-loaded map
// module. The two accessible tables are the a11y + data target here; the map's visual
// render and keyboard behaviour are covered by the separate Playwright browser suite.
vi.mock("../features/map/DistributionMap", () => ({
  default: function DistributionMapStub() {
    return null;
  },
}));

function renderApp(ui: ReactNode, route = `/species/${DEFAULT_SPECIES_ID}/${DEFAULT_SPECIES_SLUG}`) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  const { hook } = memoryLocation({ path: route });
  return render(
    <QueryClientProvider client={queryClient}>
      <Router hook={hook}>{ui}</Router>
    </QueryClientProvider>,
  );
}

describe("App — P3 slice (integration, against MSW mock)", () => {
  it(
    "renders the scoped species and BOTH the cell-summary and published-records tables with no accessibility violations",
    async () => {
      const { container } = renderApp(<App />);
      expect(await screen.findByText(/Slow-worm/, undefined, { timeout: 8000 })).toBeInTheDocument();
      const caveat = screen.getByRole("complementary", { name: "How to read this data" });
      expect(caveat).toHaveTextContent(/public capture resolution/i);
      expect(caveat).not.toHaveTextContent(/sensitive species|protected taxa|blur(?:red|ring)?|generali[sz]ed/i);
      // the map's accessible equivalent + the published individual records
      expect(await screen.findByText(/Distribution by grid square/)).toBeInTheDocument();
      expect(await screen.findByText(/Published records/)).toBeInTheDocument();
      const tables = await screen.findAllByRole("table");
      expect(tables.length).toBeGreaterThanOrEqual(2);
      const results = await axe(container);
      expect(results).toHaveNoViolations();
    },
    20000,
  );

  it("preserves the prototype landing route by redirecting to the default species", async () => {
    renderApp(<App />, "/");
    expect(await screen.findByRole("heading", { name: /Slow-worm/, level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← All species" })).toHaveAttribute("href", "/species");
  });

  it("navigates from a human-readable directory link while fetching detail by opaque species ID", async () => {
    renderApp(<App />, "/species");
    const link = await screen.findByRole("link", { name: /Explore Adder/i });
    expect(link).toHaveAttribute("href", "/species/DEMO-002/vipera-berus");
    fireEvent.click(link);
    expect(await screen.findByRole("heading", { name: /Adder/, level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Vipera berus")).toBeInTheDocument();
  });
});
