import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EmptyState, ErrorState, LoadingState } from "./States";

describe("state components", () => {
  it("renders a loading state with polite status semantics", () => {
    render(<LoadingState label="records" />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Loading records…")).toBeInTheDocument();
  });

  it("renders an empty state with a clear title and explanation", () => {
    render(<EmptyState title="No species found" message="Try changing your filters." />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("No species found")).toBeInTheDocument();
    expect(screen.getByText("Try changing your filters.")).toBeInTheDocument();
  });

  it("renders an error state with an alert and retry action", () => {
    const onRetry = vi.fn();
    render(<ErrorState message="Could not load data" onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
