import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";
import RecordsByYearChart from "./RecordsByYearChart";
import { DEFAULT_SPECIES_ID } from "../../test/fixtures";

// Recharts needs layout measurement that jsdom lacks; the visual plot is verified in the
// browser (Playwright). Here we test the ACCESSIBLE interface: the equivalent table.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("recharts");
  return { ...actual, ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div style={{ width: 600, height: 220 }}>{children}</div> };
});

function renderChart(props: { selectedYear?: number | null; onSelectYear?: (y: number | null) => void } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <RecordsByYearChart speciesId={DEFAULT_SPECIES_ID} selectedYear={props.selectedYear ?? null} onSelectYear={props.onSelectYear ?? (() => {})} />
    </QueryClientProvider>,
  );
}

describe("RecordsByYearChart", () => {
  it("renders an accessible equivalent table with a year button, and no axe violations", async () => {
    const { container } = renderChart();
    expect(await screen.findByRole("heading", { name: /Records submitted by year/ }, { timeout: 8000 })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /2024/ })).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("labels the plot with a text summary (never colour/vision alone)", async () => {
    renderChart();
    const plot = await screen.findByRole("img", undefined, { timeout: 8000 });
    expect(plot.getAttribute("aria-label")).toMatch(/records submitted per year/i);
  });

  it("selecting a year button reports it to the parent", async () => {
    const onSelectYear = vi.fn();
    renderChart({ onSelectYear });
    fireEvent.click(await screen.findByRole("button", { name: /2024/ }, { timeout: 8000 }));
    expect(onSelectYear).toHaveBeenCalledWith(2024);
  });

  it("marks the selected year as pressed and offers a way back to all years", async () => {
    const onSelectYear = vi.fn();
    renderChart({ selectedYear: 2024, onSelectYear });
    const btn = await screen.findByRole("button", { name: /2024/ }, { timeout: 8000 });
    expect(btn).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(btn);
    expect(onSelectYear).toHaveBeenCalledWith(null); // toggles back to all years
  });
});
