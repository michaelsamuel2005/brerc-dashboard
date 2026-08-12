import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { axe } from "jest-axe";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { Router, useLocation, useSearch } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { buildSpeciesListPage } from "../../test/fixtures";
import { server } from "../../test/msw/server";
import { SpeciesList } from "./SpeciesList";

function LocationProbe() {
  const [location] = useLocation();
  const search = useSearch();
  return <output data-testid="location">{location}{search ? `?${search}` : ""}</output>;
}

function renderDirectory(initialEntry = "/species") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  const { hook } = memoryLocation({ path: initialEntry });
  return render(
    <QueryClientProvider client={queryClient}>
      <Router hook={hook}>
        <SpeciesList />
        <LocationProbe />
      </Router>
    </QueryClientProvider>,
  );
}

describe("SpeciesList — server-driven public directory", () => {
  it("renders authoritative facets and canonical ID + slug links without accessibility violations", async () => {
    const { container } = renderDirectory();

    const adderLink = await screen.findByRole("link", { name: /Explore Adder/i });
    expect(adderLink).toHaveAttribute("href", "/species/DEMO-002/vipera-berus");
    expect(screen.getByRole("option", { name: "Mammals (1)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Reptiles (3)" })).toBeInTheDocument();
    expect(screen.getByText("4 species found")).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("searches, sorts and groups through URL-backed server queries", async () => {
    renderDirectory();
    await screen.findByRole("link", { name: /Explore Adder/i });

    fireEvent.change(screen.getByLabelText(/Search by common or scientific name/i), {
      target: { value: "zootoca" },
    });
    fireEvent.submit(screen.getByRole("search", { name: /Filter the species directory/i }));

    expect(await screen.findByRole("link", { name: /Explore Common lizard/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("q=zootoca"));
    expect(screen.queryByRole("link", { name: /Explore Adder/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Clear filters/i }));
    await screen.findByRole("link", { name: /Explore Adder/i });
    fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "records-desc" } });

    await screen.findByRole("link", { name: /Explore West European hedgehog/i });
    await waitFor(() => {
      const names = screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent);
      expect(names).toEqual(["West European hedgehog", "Common lizard", "Slow-worm"]);
    });

    fireEvent.change(screen.getByLabelText("Group"), { target: { value: "reptile" } });
    await screen.findByRole("link", { name: /Explore Adder/i });
    await waitFor(() => expect(screen.queryByText("West European hedgehog")).not.toBeInTheDocument());
    expect(screen.getByTestId("location")).toHaveTextContent("group=reptile");
    expect(screen.getByTestId("location")).toHaveTextContent("sort=records-desc");
  });

  it("paginates without losing filters and resets the page when a filter changes", async () => {
    renderDirectory("/species?sort=records-desc");
    await screen.findByRole("link", { name: /Explore West European hedgehog/i });

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: /Explore Adder/i })).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("sort=records-desc");
    expect(screen.getByTestId("location")).toHaveTextContent("page=2");

    fireEvent.change(screen.getByLabelText("Group"), { target: { value: "reptile" } });
    expect(await screen.findByRole("link", { name: /Explore Common lizard/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("location")).not.toHaveTextContent("page="));
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("keeps the controls usable through empty and recoverable error states", async () => {
    const view = renderDirectory();
    await screen.findByRole("link", { name: /Explore Adder/i });

    fireEvent.change(screen.getByLabelText(/Search by common or scientific name/i), {
      target: { value: "does-not-exist" },
    });
    fireEvent.submit(screen.getByRole("search"));
    expect(await screen.findByText("No species match your filters.")).toBeInTheDocument();
    expect(screen.getByLabelText("Sort")).toBeInTheDocument();

    view.unmount();
    let fail = true;
    server.use(
      http.get("*/api/species", () =>
        fail
          ? HttpResponse.json({ error: "Temporary directory failure" }, { status: 400 })
          : HttpResponse.json(buildSpeciesListPage({ pageSize: 3 })),
      ),
    );
    renderDirectory();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Request failed \(400\)/i);
    expect(screen.getByLabelText(/Search by common or scientific name/i)).toBeInTheDocument();

    fail = false;
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: /Explore Adder/i })).toBeInTheDocument();
  });
});
