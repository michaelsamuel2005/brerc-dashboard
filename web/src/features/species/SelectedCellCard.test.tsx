import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SelectedCellCard } from "./SelectedCellCard";

const api = vi.hoisted(() => ({ useDistributionCells: vi.fn() }));
vi.mock("../../lib/api", () => api);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const cell = { cellId: "ST5872", precisionMetres: 1000, recordCount: 20 };

describe("SelectedCellCard verification availability", () => {
  it("labels verification unavailable without inventing a zero", () => {
    api.useDistributionCells.mockReturnValue({
      data: { verificationAvailable: false, cells: [cell] },
    });

    render(
      <SelectedCellCard
        speciesId="DEMO-001"
        selectedCellId="ST5872"
        onClear={vi.fn()}
      />,
    );

    expect(screen.getByText("Verification unavailable")).toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.queryByText("0", { exact: true })).not.toBeInTheDocument();
  });

  it("shows count and percentage only when verification is available", () => {
    api.useDistributionCells.mockReturnValue({
      data: {
        verificationAvailable: true,
        cells: [{ ...cell, verifiedCount: 15 }],
      },
    });

    render(
      <SelectedCellCard
        speciesId="DEMO-001"
        selectedCellId="ST5872"
        onClear={vi.fn()}
      />,
    );

    expect(screen.getByText("15 (75%)")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });
});
