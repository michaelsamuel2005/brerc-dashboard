import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { server } from "../../test/msw/server";
import { SpeciesList } from "./SpeciesList";

function renderList(pageSize?: number) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<SpeciesList pageSize={pageSize} />} />
          <Route path="/species/:speciesId" element={<p>Slow-worm detail page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SpeciesList", () => {
  it(
    "lists species as real, keyboard-activatable links to /species/:speciesId, accessibly",
    async () => {
      const { container } = renderList();
      const link = await screen.findByRole("link", { name: /Slow-worm/, timeout: 8000 } as never);
      expect(link).toHaveAttribute("href", "/species/anguis-fragilis");
      expect(link).toHaveTextContent("reptile");
      expect(link).toHaveTextContent("1994–2024");

      await userEvent.tab();
      // Keep tabbing until the Slow-worm link is focused, proving it's keyboard-reachable.
      let guard = 0;
      while (document.activeElement !== link && guard < 20) {
        await userEvent.tab();
        guard += 1;
      }
      expect(link).toHaveFocus();

      await userEvent.keyboard("{Enter}");
      expect(await screen.findByText("Slow-worm detail page")).toBeInTheDocument();

      expect(await axe(container)).toHaveNoViolations();
    },
    15000,
  );

  it("shows the EmptyState when no species match", async () => {
    server.use(http.get("*/api/species", () => HttpResponse.json({ items: [], page: 1, pageSize: 20, total: 0 })));

    renderList();

    expect(await screen.findByText("No species match your filters.")).toBeInTheDocument();
  });

  it(
    "paginates the list with an accessible, keyboard-operable Prev/Next control",
    async () => {
      const user = userEvent.setup();
      renderList(2);

      await screen.findByRole("link", { name: /Slow-worm/ });
      expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();

      const prevButton = screen.getByRole("button", { name: /previous/i });
      const nextButton = screen.getByRole("button", { name: /next/i });
      expect(prevButton).toBeDisabled();
      expect(nextButton).not.toBeDisabled();

      nextButton.focus();
      await user.keyboard("{Enter}");

      expect(await screen.findByText("Page 2 of 2")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Hedgehog/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();

      const { container } = renderList(2);
      await screen.findByRole("link", { name: /Slow-worm/ });
      expect(await axe(container)).toHaveNoViolations();
    },
    15000,
  );
});
