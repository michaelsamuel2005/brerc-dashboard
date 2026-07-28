import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";
import { EmptyState, ErrorState, LoadingState } from "./States";

describe("state components", () => {
  it("renders a loading state with polite status semantics", async () => {
    const { container } = render(<LoadingState label="records" />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(await screen.findByText("Loading records…")).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("renders an empty state with a clear title and explanation", async () => {
    const { container } = render(<EmptyState title="No species found" message="Try changing your filters." />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("No species found")).toBeInTheDocument();
    expect(await screen.findByText("Try changing your filters.")).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("renders an error state with an alert and a working, keyboard-operable retry action", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const { container } = render(<ErrorState message="Could not load data" onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Could not load data")).toBeInTheDocument();

    const retryButton = screen.getByRole("button", { name: /try again/i });
    await user.tab();
    expect(retryButton).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onRetry).toHaveBeenCalledTimes(1);

    expect(await axe(container)).toHaveNoViolations();
  });
});
