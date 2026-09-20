import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RecordsTable } from "./RecordsTable";

const api = vi.hoisted(() => ({
  useRecords: vi.fn(),
  toAsyncState: vi.fn((value: unknown) => value),
}));

vi.mock("../../lib/api", () => api);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const baseRow = {
  id: "public-record-1",
  scientificName: "Anguis fragilis",
  commonName: "Slow-worm",
  gridRef: "ST585725",
  precisionMetres: 100,
  place: null,
  year: 2024,
  source: "BRERC",
};

function fields(
  recordType: boolean,
  verification: boolean,
  abundance = false,
  place = false,
) {
  return {
    abundance,
    place,
    recordType,
    verification,
  };
}

function ready(data: unknown) {
  api.useRecords.mockReturnValue({ status: "ready", data });
}

describe("RecordsTable publication states", () => {
  it("states that individual records are not published instead of claiming zero records", () => {
    ready({
      publication: {
        mode: "aggregates-only",
        fields: fields(false, false),
      },
      items: [],
      page: 1,
      pageSize: 20,
      total: 0,
    });

    render(<RecordsTable speciesId="DEMO-001" />);

    expect(screen.getByRole("heading", { name: "Individual records" })).toBeInTheDocument();
    expect(screen.getByText(/Individual records are not published/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(/sample/i)).not.toBeInTheDocument();
  });

  it("labels enabled output as published records and renders approved optional columns", () => {
    ready({
      publication: {
        mode: "individual-records",
        fields: fields(true, true, true, true),
      },
      items: [{
        ...baseRow,
        place: "Approved public place",
        abundance: "3",
        recordType: "field observation",
        verified: "accepted",
      }],
      page: 1,
      pageSize: 20,
      total: 1,
    });

    render(<RecordsTable speciesId="DEMO-001" />);

    expect(screen.getByRole("heading", { name: "Published records" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Place" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Abundance" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Record type" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Verified" })).toBeInTheDocument();
    expect(screen.getByText("field observation")).toBeInTheDocument();
    expect(screen.getByText("Approved public place")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.queryByText(/sample/i)).not.toBeInTheDocument();
  });

  it("omits record-type and verification columns when they are not published", () => {
    ready({
      publication: {
        mode: "individual-records",
        fields: fields(false, false),
      },
      items: [baseRow],
      page: 1,
      pageSize: 20,
      total: 1,
    });

    render(<RecordsTable speciesId="DEMO-001" />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Place" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Abundance" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Record type" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Verified" })).not.toBeInTheDocument();
  });

  it("distinguishes an empty published-record result from aggregates-only policy", () => {
    ready({
      publication: {
        mode: "individual-records",
        fields: fields(false, false),
      },
      items: [],
      page: 1,
      pageSize: 20,
      total: 0,
    });

    render(<RecordsTable speciesId="DEMO-001" year={2024} />);

    expect(screen.getByRole("heading", { name: "Published records" })).toBeInTheDocument();
    expect(screen.getByText("No individual records are published for 2024.")).toBeInTheDocument();
    expect(screen.queryByText(/not published\. The distribution/i)).not.toBeInTheDocument();
  });
});
