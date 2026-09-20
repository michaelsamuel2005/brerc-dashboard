import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { summaryFixture } from "../../test/fixtures";
import { server } from "../../test/msw/server";
import { OverviewPage } from "./OverviewPage";

function renderOverview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const { hook } = memoryLocation({ path: "/" });
  const wrap = (children: ReactNode) => (
    <QueryClientProvider client={client}>
      <Router hook={hook}>{children}</Router>
    </QueryClientProvider>
  );
  return render(wrap(<OverviewPage />));
}

/**
 * Ported from PR #19 (summary-bar, Athul). That branch built a standalone summary
 * banner; the overview's KPI row and charts superseded the component, but two of the
 * behaviours its tests pinned were not covered anywhere on the page that replaced it:
 * the headline figures must come from the release rather than typed literals, and a
 * failed summary must leave the reader a working, keyboard-operable way back. Athul's
 * method is kept — every expected value is derived from the fixture the mock serves,
 * so the tests stay correct when the fixture changes. (His third behaviour, a
 * "No summary available" empty state, does not port: the overview deliberately renders
 * zeros as zeros rather than declaring emptiness.)
 */
describe("OverviewPage — summary figures and recovery (ported from PR #19)", () => {
  it("renders the release's totals, year range and coverage caveat, derived from the fixture", async () => {
    renderOverview();

    expect(
      await screen.findByText(summaryFixture.totalRecords.toLocaleString("en-GB")),
    ).toBeInTheDocument();
    expect(screen.getByText("Records published")).toBeInTheDocument();
    expect(screen.getByText("Species")).toBeInTheDocument();
    expect(
      screen.getAllByText(summaryFixture.totalSpecies.toLocaleString("en-GB")).length,
    ).toBeGreaterThan(0);
    // The fixture's yearRange is nullable in the type (a release may publish no yearly
    // totals); this test is about the fixture that IS served, so assert it exists first.
    const { yearRange } = summaryFixture;
    if (!yearRange) throw new Error("summaryFixture.yearRange missing: fixture changed");
    expect(screen.getByText(`${yearRange.min}–${yearRange.max}`)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(summaryFixture.coverageCaveat.slice(0, 40)))).toBeInTheDocument();
  });

  it("shows an alert with a keyboard-operable retry when the summary fails, and recovers", async () => {
    // 503 rather than Athul's original 400, deliberately: it is the error a reader will
    // actually meet — the publication store answers 503 whenever no release is active.
    // It also exercises the bounded-retry policy in lib/api/queries.ts: a 5xx is retried
    // twice with backoff before the alert appears, hence the extended timeout below.
    // (A 4xx would surface instantly and skip that path.)
    server.use(
      http.get("*/api/summary", () => HttpResponse.json({ error: "boom" }, { status: 503 })),
    );
    const user = userEvent.setup();
    renderOverview();

    expect(await screen.findByRole("alert", {}, { timeout: 8000 })).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: /try again/i });
    // A real <button>: Enter/Space activation is a browser guarantee, not a listener's
    // promise — the same property the PR #23 port pins on the directory's pagination.
    expect(retry.tagName).toBe("BUTTON");

    // The server heals; the reader's next attempt must succeed via the keyboard alone.
    server.use(http.get("*/api/summary", () => HttpResponse.json(summaryFixture)));
    retry.focus();
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText(summaryFixture.totalRecords.toLocaleString("en-GB"), undefined, {
        timeout: 4000,
      }),
    ).toBeInTheDocument();
  });
});
