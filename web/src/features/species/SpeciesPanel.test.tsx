import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SpeciesPanel } from "./SpeciesPanel";

const api = vi.hoisted(() => ({
  useSpeciesDetail: vi.fn(),
  toAsyncState: vi.fn((value: unknown) => value),
}));

vi.mock("../../lib/api", () => api);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const detail = {
  speciesId: "DEMO-001",
  slug: "anguis-fragilis",
  scientificName: "Anguis fragilis",
  commonName: "Slow-worm",
  group: "Reptile",
  imagePublication: "fallback-only" as const,
  stats: {
    recordCount: 186,
    yearRange: [1995, 2024] as [number, number],
    verificationAvailable: false,
    verifiedCount: null,
  },
};

describe("SpeciesPanel verification availability", () => {
  it("states honestly when the source cannot supply verification totals", () => {
    api.useSpeciesDetail.mockReturnValue({ status: "ready", data: detail });

    render(<SpeciesPanel speciesId="DEMO-001" />);

    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.getByText("Verification unavailable")).toBeInTheDocument();
    expect(screen.queryByText("0", { exact: true })).not.toBeInTheDocument();
  });

  it("shows the verified total only when verification is available", () => {
    api.useSpeciesDetail.mockReturnValue({
      status: "ready",
      data: {
        ...detail,
        stats: { ...detail.stats, verificationAvailable: true, verifiedCount: 178 },
      },
    });

    render(<SpeciesPanel speciesId="DEMO-001" />);

    expect(screen.getByText("178")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.queryByText("Verification unavailable")).not.toBeInTheDocument();
  });

  it("shows a credited description only when its provenance accompanies it", () => {
    api.useSpeciesDetail.mockReturnValue({
      status: "ready",
      data: {
        ...detail,
        description: "Synthetic description for the component test.",
        descriptionSource: {
          label: "Synthetic demonstration content",
          sourceUrl: "https://example.test/description",
          licence: "CC0 1.0",
          licenceUrl: "https://creativecommons.org/publicdomain/zero/1.0/",
          approvalReference: "synthetic-fixture-only",
        },
      },
    });

    render(<SpeciesPanel speciesId="DEMO-001" />);

    expect(screen.getByText("Synthetic description for the component test.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Synthetic demonstration content" })).toHaveAttribute(
      "href",
      "https://example.test/description",
    );
    expect(screen.getByRole("link", { name: "CC0 1.0" })).toBeInTheDocument();
    expect(screen.queryByText("Description unavailable.")).not.toBeInTheDocument();
  });

  it("states when no approved description is available", () => {
    api.useSpeciesDetail.mockReturnValue({ status: "ready", data: detail });

    render(<SpeciesPanel speciesId="DEMO-001" />);

    expect(screen.getByText("Description unavailable.")).toBeInTheDocument();
  });
});
