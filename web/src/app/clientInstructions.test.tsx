import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ReactNode } from "react";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";

// Instructions BRERC gave at client meeting 2, as tests.
//
// Every one of these was already built the other way round, from the mid-review
// prototype, before the meeting record reached us. A comment saying "BRERC asked for
// this" does not survive a refactor by someone who was not in the room; an assertion
// does. Each test below quotes the instruction it enforces.

vi.mock("../features/map/DistributionMap", () => ({
  default: function DistributionMapStub() {
    return null;
  },
}));

function renderAt(route: string, ui: ReactNode = <App />) {
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

const PUBLIC_ROUTES = [
  "/",
  "/species",
  "/records",
  "/records?species=DEMO-002",
  "/about",
  "/accessibility",
  "/settings",
];

describe('"Remove the export button. BRERC does not want people exporting directly from the dashboard."', () => {
  it.each(PUBLIC_ROUTES)("offers no download or export control on %s", async (route) => {
    renderAt(route);
    await screen.findByRole("heading", { level: 1 });
    for (const control of [...screen.queryAllByRole("button"), ...screen.queryAllByRole("link")]) {
      expect(control.textContent ?? "").not.toMatch(/download|export|\.csv/i);
    }
    // A download can also be an anchor with the attribute and no matching text.
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
  });

  it("no longer ships a CSV module for anything to import", () => {
    // Deleted rather than left unused: an unused export path is what gets switched back
    // on later. Vite resolves this at build time, so a stale import fails the build too.
    expect(() => readFileSync(resolve(process.cwd(), "src/features/records/csv.ts"), "utf8")).toThrow();
  });
});

describe('"They do not like the top-10 ranking within the region, meaning no number of records per square."', () => {
  it("offers no way to order grid squares by record count", async () => {
    renderAt("/records?species=DEMO-002");
    const order = await screen.findByLabelText("Order by");
    const options = [...order.querySelectorAll("option")];
    expect(options.length).toBeGreaterThan(0);
    for (const option of options) {
      expect(option.value).not.toMatch(/records/i);
      expect(option.textContent ?? "").not.toMatch(/records|most|top|rank/i);
    }
  });

  it("defaults to grid-square order", async () => {
    renderAt("/records?species=DEMO-002");
    const order = await screen.findByLabelText("Order by");
    expect((order as HTMLSelectElement).value).toBe("grid-asc");
  });

  it("still shows the record count per square, which they liked", async () => {
    // The objection was to ranking by the number, not to the number. Removing it as well
    // would be over-reading the instruction.
    renderAt("/records?species=DEMO-002");
    expect(await screen.findByRole("columnheader", { name: "Records" })).toBeInTheDocument();
  });
});

describe('"The serif font needs changing." / "The overall style could be more modern."', () => {
  const css = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");

  it("sets no serif family on the display face", () => {
    const match = /--display\s*:\s*([^;]+);/.exec(css);
    expect(match?.[1], "--display not found in tokens.css").toBeDefined();
    const stack = match![1]!.toLowerCase();
    // "sans-serif" is the generic fallback and is fine; a bare "serif", or a named serif
    // family, is not. The negative lookbehind is what distinguishes them.
    expect(stack).not.toMatch(/(?<!sans-)\bserif\b/);
    expect(stack).not.toMatch(/fraunces|georgia|times|garamond|palatino/);
  });

  it("does not depend on the serif package any more", () => {
    const pkg = JSON.parse(readFileSync(resolve(process.cwd(), "package.json"), "utf8")) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    const all = { ...pkg.dependencies, ...pkg.devDependencies };
    expect(Object.keys(all).join(" ")).not.toMatch(/fraunces/i);
  });
});

describe('"The explanation of how sensitive species locations are blurred is to be removed."', () => {
  // The mechanism, not the meaning. Each square still states its capture resolution —
  // removing that would leave the map claiming a precision it does not have.
  const MECHANISM = /generali[sz]|blurred|blurring|coarse grid|snapped|before it (?:ever )?reach/i;

  it.each(["/", "/species", "/records", "/about", "/accessibility", "/settings"])(
    "says nothing about how it is done on %s",
    async (route) => {
      const { container } = renderAt(route);
      await screen.findByRole("heading", { level: 1 });
      expect(container.textContent ?? "").not.toMatch(MECHANISM);
    },
  );

  it("keeps capture resolution, in BRERC's own wording", async () => {
    // "BRERC uses the term 'capture' for resolution, so it should read 'capture
    // resolution'." — the same meeting.
    renderAt("/records?species=DEMO-002");
    expect(await screen.findByRole("columnheader", { name: "Capture resolution" })).toBeInTheDocument();
  });

  it("keeps one sentence in the privacy notice, as a flagged recommendation", async () => {
    // Deliberately the single exception, and it says only THAT it happens. A statutory
    // notice silent on processing that does occur is a weaker document. Tim can strike
    // it; until he does, this asserts we have not quietly dropped it either.
    const { container } = renderAt("/privacy");
    await screen.findByRole("heading", { level: 1 });
    expect(container.textContent ?? "").toMatch(/generalised before publication/i);
  });
});

describe('"BRERC was confused by... the data source section, because the only data source is BRERC."', () => {
  it("names one holder and no source list", async () => {
    const { container } = renderAt("/");
    // The strip renders only once /api/meta/provenance resolves, so wait for it rather
    // than asserting against a page that has not finished loading.
    await screen.findByText(/Records held by/i);
    expect(container.textContent ?? "").toMatch(/Records held by\s*BRERC/i);
    // The fixture's second label. If a list ever comes back, this catches it.
    expect(container.textContent ?? "").not.toMatch(/Consultancy submissions/i);
  });
});

describe('"BRERC holds roughly 15,000-16,000 species."', () => {
  it.each([
    ["/records", "records-species-search"],
    ["/explore", "explore-species-search"],
  ])("chooses a species by searching on %s, not from a dropdown", async (route, inputId) => {
    renderAt(route);
    await screen.findByRole("heading", { level: 1 });
    const input = await screen.findByLabelText("Search species");
    expect(input).toHaveAttribute("id", inputId);
    expect(input.tagName).toBe("INPUT");
    // The control this replaces: a <select> cannot hold 16,000 options, and one holding
    // the first hundred looks complete while answering a different question. Assert on
    // form controls only — a <section> may still be *labelled* "Species", which is a
    // heading, not a picker.
    for (const select of document.querySelectorAll("select")) {
      const label = select.labels?.[0]?.textContent ?? "";
      expect(label).not.toMatch(/^\s*Species\s*$/i);
    }
  });
});
