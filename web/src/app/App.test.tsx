import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { Providers } from "./providers";

describe("App (integration, against MSW mock)", () => {
  it("renders live data from the mock and has no accessibility violations", async () => {
    const { container } = render(
      <Providers>
        <App />
      </Providers>,
    );
    // Data flows: species list from the mock API
    expect(await screen.findByText(/Slow-worm/)).toBeInTheDocument();
    // Records table (R5 fallback) renders the same source
    expect(await screen.findByRole("table")).toBeInTheDocument();
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
