import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";
import { Legend } from "./Legend";

describe("Legend", () => {
  it("is collapsed by default, expands on request, labels every band in text, and is accessible", async () => {
    const user = userEvent.setup();
    const { container } = render(<Legend />);
    const summary = screen.getByRole("button", { name: "Map key" });
    const content = container.querySelector("#map-key-content");
    expect(content).not.toBeNull();
    expect(summary).toHaveAttribute("aria-expanded", "false");
    expect(content).not.toBeVisible();
    summary.focus();
    expect(summary).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(summary).toHaveAttribute("aria-expanded", "true");
    expect(content).toBeVisible();
    expect(screen.getByText("Records in each displayed grid square")).toBeInTheDocument();
    expect(screen.getByText(/The squares are translucent so the map remains visible\./)).toBeInTheDocument();
    expect(screen.getByText(/1–5 records/)).toBeInTheDocument();
    expect(screen.getByText(/51\+ records/)).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
    await user.keyboard(" ");
    expect(summary).toHaveAttribute("aria-expanded", "false");
    expect(content).not.toBeVisible();
    expect(summary).toHaveFocus();
  });
});
