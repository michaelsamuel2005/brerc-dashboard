import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MapInstructions } from "./MapInstructions";

describe("MapInstructions", () => {
  it("explains pointer, touch, button and table alternatives", () => {
    render(<MapInstructions />);

    expect(screen.getByText(/Using the map\./)).toBeInTheDocument();
    expect(screen.getByText(/Tap or click a green square/)).toBeInTheDocument();
    expect(screen.getByText(/Use \+\/− to zoom and the arrow buttons/)).toBeInTheDocument();
    expect(screen.getByText(/use two fingers to move it/i)).toBeInTheDocument();
    expect(screen.getByText(/choose a square in the table below/i)).toBeInTheDocument();
  });
});
