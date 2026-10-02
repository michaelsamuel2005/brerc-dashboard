import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { CellSummaryTable } from "./CellSummaryTable";
import { DEFAULT_SPECIES_ID, fixtureReleaseIdentity } from "../../test/fixtures";
import { server } from "../../test/msw/server";

function renderIt(props: { speciesId: string; selectedCellId?: string | null; onSelectCell?: (id: string | null) => void }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <CellSummaryTable {...props} />
    </QueryClientProvider>,
  );
}

describe("CellSummaryTable (map accessible equivalent + keyboard control)", () => {
  it(
    "lists each grid square from the same cells data, accessibly",
    async () => {
      const { container } = renderIt({ speciesId: DEFAULT_SPECIES_ID });
      expect(await screen.findByRole("button", { name: /ST5872/ })).toBeInTheDocument();
      expect(await screen.findByRole("table")).toBeInTheDocument();
      expect(await axe(container)).toHaveNoViolations();
    },
    15000,
  );

  it(
    "selecting a square's button reports its id to the parent",
    async () => {
      const onSelectCell = vi.fn();
      renderIt({ speciesId: DEFAULT_SPECIES_ID, onSelectCell });
      const btn = await screen.findByRole("button", { name: /ST5872/ });
      fireEvent.click(btn);
      expect(onSelectCell).toHaveBeenCalledWith("ST5872");
    },
    15000,
  );

  it(
    "marks the selected square's button as pressed and its row as selected",
    async () => {
      const { container } = renderIt({ speciesId: DEFAULT_SPECIES_ID, selectedCellId: "ST5872" });
      const btn = await screen.findByRole("button", { name: /ST5872/ });
      expect(btn).toHaveAttribute("aria-pressed", "true");
      expect(container.querySelector("tr.selected")).toHaveTextContent("ST5872");
    },
    15000,
  );

  it(
    "shows an empty state for an unknown/unscoped species (proves scoping)",
    async () => {
      renderIt({ speciesId: "not-a-species" });
      expect(await screen.findByText(/No mapped records/, undefined, { timeout: 8000 })).toBeInTheDocument();
    },
    15000,
  );

  it("omits the verified column and explains when the source has no verification field", async () => {
    server.use(
      http.get("*/api/distribution/cells", () =>
        HttpResponse.json({
          ...fixtureReleaseIdentity,
          verificationAvailable: false,
          cells: [{ cellId: "ST5872", precisionMetres: 1000, recordCount: 2 }],
        }),
      ),
    );

    renderIt({ speciesId: DEFAULT_SPECIES_ID });

    expect(await screen.findByRole("button", { name: /ST5872/ })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Verified" })).not.toBeInTheDocument();
    expect(screen.getByText(/Verification information is not available from the source data/)).toBeInTheDocument();
  });
});
