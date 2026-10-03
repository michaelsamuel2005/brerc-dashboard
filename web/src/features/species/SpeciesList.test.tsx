import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
      // All four fixture species now fit one page: BRERC hold 15,000-16,000 species and
      // asked for a layout showing several at a time, so PAGE_SIZE went from 3 to 24.
      // Ordered by record count, descending.
      expect(names).toEqual(["West European hedgehog", "Common lizard", "Slow-worm", "Adder"]);
    });

    fireEvent.change(screen.getByLabelText("Group"), { target: { value: "reptile" } });
    await screen.findByRole("link", { name: /Explore Adder/i });
    await waitFor(() => expect(screen.queryByText("West European hedgehog")).not.toBeInTheDocument());
    expect(screen.getByTestId("location")).toHaveTextContent("group=reptile");
    expect(screen.getByTestId("location")).toHaveTextContent("sort=records-desc");
  });

  it("paginates without losing filters and resets the page when a filter changes", async () => {
    // Driven by a server that reports far more species than it returns, rather than by
    // the fixture happening to be one item longer than a page. That coupling is what
    // broke when PAGE_SIZE changed, and it would break again at the real catalogue size.
    const pages = new Map<string, string[]>([
      ["1", ["West European hedgehog", "Common lizard"]],
      ["2", ["Slow-worm", "Adder"]],
    ]);
    server.use(
      http.get("*/api/species", ({ request }) => {
        const params = new URL(request.url).searchParams;
        const wanted = pages.get(params.get("page") ?? "1") ?? [];
        const page = buildSpeciesListPage({
          q: "",
          sort: "records-desc",
          page: 1,
          pageSize: 24,
          ...(params.get("group") ? { group: params.get("group") ?? undefined } : {}),
        });
        const items = page.items.filter((item) =>
          wanted.includes(item.commonName ?? item.scientificName),
        );
        // A total larger than one page, so the control has somewhere to go.
        return HttpResponse.json({ ...page, items, page: Number(params.get("page") ?? 1), total: 400 });
      }),
    );

    renderDirectory("/species?sort=records-desc");
    await screen.findByRole("link", { name: /Explore West European hedgehog/i });

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: /Explore Slow-worm/i })).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("sort=records-desc");
    expect(screen.getByTestId("location")).toHaveTextContent("page=2");

    fireEvent.change(screen.getByLabelText("Group"), { target: { value: "reptile" } });
    await waitFor(() => expect(screen.getByTestId("location")).not.toHaveTextContent("page="));
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("asks the server for a page a reader can actually use", async () => {
    // BRERC hold roughly 15,000-16,000 species (client meeting 2) and said scrolling a
    // list that long takes too long. Three per page would be 5,333 pages of catalogue.
    let requestedPageSize: string | null = null;
    server.use(
      http.get("*/api/species", ({ request }) => {
        requestedPageSize = new URL(request.url).searchParams.get("pageSize");
        return HttpResponse.json(
          buildSpeciesListPage({ q: "", sort: "name-asc", page: 1, pageSize: 24 }),
        );
      }),
    );
    renderDirectory();
    await screen.findByRole("link", { name: /Explore Adder/i });
    expect(Number(requestedPageSize)).toBeGreaterThanOrEqual(12);
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

/**
 * Ported from PR #23 (species-index, Athul). That branch pinned two behaviours the
 * directory rebuild had left untested — every species entry is a REAL, keyboard-reachable
 * link, and pagination works without a pointer. The implementation Athul tested was
 * superseded by the server-driven directory, but the properties are implementation-
 * independent, so they are re-stated here against the current markup rather than lost
 * with the branch. Method preserved too: real Tab keys and a real Enter, not synthetic
 * click() calls — a click handler on a div would pass those and still fail a keyboard.
 */
describe("SpeciesList — keyboard operability (ported from PR #23)", () => {
  it("reaches and activates a species link with the keyboard alone", async () => {
    const user = userEvent.setup();
    renderDirectory();
    const link = await screen.findByRole("link", { name: /Explore Slow-worm/i });
    expect(link).toHaveAttribute("href", "/species/DEMO-001/anguis-fragilis");

    // Tab until the link is focused, proving it is reachable in the natural order —
    // bounded so a regression fails with "not focused" instead of hanging the suite.
    let guard = 0;
    await user.tab();
    while (document.activeElement !== link && guard < 40) {
      await user.tab();
      guard += 1;
    }
    expect(link).toHaveFocus();

    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/species/DEMO-001/anguis-fragilis",
      ),
    );
  });

  it("operates the Prev/Next pagination with the keyboard alone", async () => {
    // Same shape as the pointer pagination test above: a server that reports more
    // species than it returns, so the control genuinely has somewhere to go.
    const pages = new Map<string, string[]>([
      ["1", ["West European hedgehog", "Common lizard"]],
      ["2", ["Slow-worm", "Adder"]],
    ]);
    server.use(
      http.get("*/api/species", ({ request }) => {
        const params = new URL(request.url).searchParams;
        const wanted = pages.get(params.get("page") ?? "1") ?? [];
        const page = buildSpeciesListPage({ q: "", sort: "records-desc", page: 1, pageSize: 24 });
        const items = page.items.filter((item) =>
          wanted.includes(item.commonName ?? item.scientificName),
        );
        return HttpResponse.json({
          ...page,
          items,
          page: Number(params.get("page") ?? 1),
          total: 400,
        });
      }),
    );

    const user = userEvent.setup();
    renderDirectory("/species?sort=records-desc");
    await screen.findByRole("link", { name: /Explore West European hedgehog/i });

    const next = screen.getByRole("button", { name: "Next" });
    // A real <button> activates on Enter and Space natively; a div with role="button"
    // and a click handler would satisfy the role query and silently lose that.
    expect(next.tagName).toBe("BUTTON");
    next.focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("link", { name: /Explore Slow-worm/i })).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("page=2");
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
  });
});
