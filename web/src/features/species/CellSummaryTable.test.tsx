import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";
import { CellSummaryTable } from "./CellSummaryTable";

function renderIt(speciesId: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <CellSummaryTable speciesId={speciesId} />
    </QueryClientProvider>,
  );
}

describe("CellSummaryTable (the map's accessible equivalent)", () => {
  it(
    "lists each grid square from the same cells data, accessibly",
    async () => {
      const { container } = renderIt("anguis-fragilis");
      expect(await screen.findByText("ST5872", undefined, { timeout: 8000 })).toBeInTheDocument();
      expect(await screen.findByRole("table")).toBeInTheDocument();
      expect(await axe(container)).toHaveNoViolations();
    },
    15000,
  );

  it(
    "shows an empty state when the request is not scoped to the known species (proves scoping)",
    async () => {
      renderIt("not-a-species");
      expect(await screen.findByText(/No mapped records/, undefined, { timeout: 8000 })).toBeInTheDocument();
    },
    15000,
  );
});
