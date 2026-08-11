import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";
import { Legend } from "./Legend";

describe("Legend", () => {
  it("labels every band in text (never colour alone) and is accessible", async () => {
    const { container } = render(<Legend />);
    expect(screen.getByText(/1–5 records/)).toBeInTheDocument();
    expect(screen.getByText(/51\+ records/)).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });
});
