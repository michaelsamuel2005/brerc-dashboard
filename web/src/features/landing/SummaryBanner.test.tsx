import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { summaryFixture } from "../../test/fixtures";
import { SummaryBar } from "./SummaryBanner";

function withQueryClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("SummaryBar", () => {
  it("renders totals, groups, and the coverage caveat once the summary loads", async () => {
    const { container } = render(withQueryClient(<SummaryBar />));

    // Assertions are derived from the fixture itself (the same data the MSW handler
    // serves), not copied-out literals — so this stays correct if the fixture changes.
    expect(await screen.findByText(summaryFixture.totalRecords.toLocaleString())).toBeInTheDocument();
    expect(screen.getByText("Records")).toBeInTheDocument();
    expect(screen.getByText(summaryFixture.totalSpecies.toLocaleString())).toBeInTheDocument();
    expect(screen.getByText("Species")).toBeInTheDocument();
    expect(screen.getByText(`${summaryFixture.yearRange.min}–${summaryFixture.yearRange.max}`)).toBeInTheDocument();

    for (const group of summaryFixture.topGroups) {
      expect(screen.getByText(group.group)).toBeInTheDocument();
      expect(screen.getByText(`${group.count.toLocaleString()} records`)).toBeInTheDocument();
    }

    expect(screen.getByText(summaryFixture.coverageCaveat)).toBeInTheDocument();

    expect(await axe(container)).toHaveNoViolations();
  });
});