import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
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
      expect(caveat).toHaveTextContent(/capture resolution/i);
      // BRERC asked at client meeting 2 for the explanation of how sensitive locations
      // are blurred to be removed from the public pages. Naming the method also tells a
      // reader which squares to be curious about, so this assertion is a safety rule and
      // not only a wording preference.
      expect(caveat).not.toHaveTextContent(
        /sensitive|protected taxa|blur(?:red|ring)?|generali[sz]/i,
      );
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

  it("lands on the overview, not a hardcoded species", async () => {
    // "/" once redirected to one named demo species. That passes against the mock,
    // whose fixture always contains it, and fails against a real publication release,
    // where the landing page renders "Request failed (404)" for a species the release
    // does not publish. Nothing on the home page may name a species in advance: the
    // featured cards come from the API, ordered by record count.
    renderApp(<App />, "/");
    expect(
      await screen.findByRole("heading", { name: /The living record of the West of England/i, level: 1 }),
    ).toBeInTheDocument();
    const featured = await screen.findAllByRole("link", { name: /^Explore / });
    expect(featured.length).toBeGreaterThan(0);
    for (const link of featured) {
      // Every destination is a real published species id, not a literal in our source.
      expect(link).toHaveAttribute("href", expect.stringMatching(/^\/species\/[^/]+\/[a-z0-9-]+$/));
    }
    expect(screen.getByRole("link", { name: "BRERC home" })).toBeInTheDocument();
    expect(screen.queryByText(/prototype/i)).not.toBeInTheDocument();
  });

  it("shows the published totals on the overview, from the API", async () => {
    renderApp(<App />, "/");
    // "Species" also names a nav link, so scope the lookup to the figures block rather
    // than matching text anywhere on the page.
    const records = await screen.findByText("Records published");
    const kpis = records.closest(".kpis");
    expect(kpis).not.toBeNull();
    for (const label of ["Records published", "Species", "Years covered", "Busiest year"]) {
      expect(within(kpis as HTMLElement).getByText(label)).toBeInTheDocument();
    }
  });

  it("reaches every page in the primary navigation", async () => {
    renderApp(<App />, "/");
    for (const name of ["Overview", "Explore", "Species", "Records", "About the data"]) {
      expect(await screen.findByRole("link", { name })).toBeInTheDocument();
    }
  });

  it.each([
    ["/about", /About the data/i],
    ["/records", /Grid-square summary/i],
    ["/settings", /Settings/i],
    ["/accessibility", /Accessibility statement/i],
    ["/privacy", /Privacy/i],
    ["/nowhere-at-all", /That page does not exist/i],
  ])("renders %s", async (route, heading) => {
    renderApp(<App />, route);
    expect(await screen.findByRole("heading", { name: heading, level: 1 })).toBeInTheDocument();
  });

  it.each([
    ["the overview", "/"],
    ["about the data", "/about"],
    ["the grid-square summary", "/records"],
    ["settings", "/settings"],
    ["the accessibility statement", "/accessibility"],
    ["the privacy notice", "/privacy"],
  ])("has no accessibility violations on %s", async (_label, route) => {
    const { container } = renderApp(<App />, route);
    // Wait for the page heading so axe runs against loaded content, not a spinner.
    await screen.findByRole("heading", { level: 1 });
    expect(await axe(container)).toHaveNoViolations();
  }, 20000);

  it("does not steal focus on a cold load, so the first Tab reaches the skip link", async () => {
    // WCAG 2.4.1. The browser already has focus at the top of the document on a fresh
    // load; moving it into the <h1> sends the first Tab PAST the skip link, making the
    // one control that exists to bypass the navigation the one control a keyboard user
    // cannot reach. The browser suite guards this too, but it only ever passed there by
    // accident of timing — this asserts the rule directly.
    renderApp(<App />, "/about");
    const heading = await screen.findByRole("heading", { name: /About the data/i, level: 1 });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(document.activeElement).not.toBe(heading);
    expect(heading).toHaveAttribute("tabindex", "-1"); // still focusable for real navigations
  });

  it("still sets the document title on a cold load", async () => {
    renderApp(<App />, "/about");
    await screen.findByRole("heading", { level: 1 });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(document.title).toMatch(/About the data \| BRERC/);
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
