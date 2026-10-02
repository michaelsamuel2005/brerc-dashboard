import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SpeciesImageSchema } from "../lib/api/schemas";
import { AttributedImage } from "./AttributedImage";

afterEach(cleanup);

const image = {
  url: "https://images.example.test/slow-worm.jpg",
  attributionText: "Photograph: Example Naturalist",
  licence: "CC0 1.0",
  licenceUrl: "https://creativecommons.org/publicdomain/zero/1.0/",
  sourceUrl: "https://images.example.test/slow-worm",
  approvalReference: "BRERC-ASSET-0001",
  alt: "A slow-worm resting among dry leaves",
};

describe("AttributedImage", () => {
  it("requires the approved per-asset attribution text instead of an author field", () => {
    expect(SpeciesImageSchema.parse(image).attributionText).toBe(
      "Photograph: Example Naturalist",
    );
    expect(() =>
      SpeciesImageSchema.parse({
        ...image,
        attributionText: undefined,
        author: "Example Naturalist",
      }),
    ).toThrow();
  });

  it("renders the exact attribution with structured licence and source links", () => {
    render(<AttributedImage image={SpeciesImageSchema.parse(image)} name="Slow-worm" />);

    expect(screen.getByText("Photograph: Example Naturalist", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(/©/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CC0 1.0" })).toHaveAttribute(
      "href",
      image.licenceUrl,
    );
    expect(screen.getByRole("link", { name: "source" })).toHaveAttribute(
      "href",
      image.sourceUrl,
    );
  });

  it("falls back honestly when no approved asset exists or the image fails", () => {
    const { rerender } = render(<AttributedImage name="Slow-worm" />);
    expect(screen.getByText("Photograph pending licence")).toBeInTheDocument();

    rerender(<AttributedImage image={SpeciesImageSchema.parse(image)} name="Slow-worm" />);
    fireEvent.error(screen.getByRole("img", { name: image.alt }));
    expect(screen.getByText("Photograph pending licence")).toBeInTheDocument();
  });
});
