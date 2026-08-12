import { type FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "wouter";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";
import { toAsyncState, useSpeciesList } from "../../lib/api";
import type { SpeciesSort } from "../../lib/api/schemas";

const PAGE_SIZE = 3;
const SORT_OPTIONS: readonly { value: SpeciesSort; label: string }[] = [
  { value: "name-asc", label: "Common name (A–Z)" },
  { value: "scientific-name-asc", label: "Scientific name (A–Z)" },
  { value: "records-desc", label: "Most records" },
  { value: "latest-record-desc", label: "Most recently recorded" },
];

function positivePage(raw: string | null): number {
  const value = Number(raw);
  return Number.isInteger(value) && value > 0 ? value : 1;
}

function speciesSort(raw: string | null): SpeciesSort {
  return SORT_OPTIONS.some((option) => option.value === raw)
    ? (raw as SpeciesSort)
    : "name-asc";
}

export function SpeciesList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const q = searchParams.get("q") ?? "";
  const group = searchParams.get("group") ?? "";
  const sort = speciesSort(searchParams.get("sort"));
  const page = positivePage(searchParams.get("page"));
  const [searchDraft, setSearchDraft] = useState(q);

  useEffect(() => setSearchDraft(q), [q]);

  const query = useSpeciesList({
    ...(q ? { q } : {}),
    ...(group ? { group } : {}),
    sort,
    page,
    pageSize: PAGE_SIZE,
  });
  const state = toAsyncState(query, (data) => data.items.length === 0);
  const groups = query.data?.facets.groups ?? [];

  function updateSearchParams(
    updates: Readonly<Record<string, string | undefined>>,
    resetPage = false,
  ) {
    const next = new URLSearchParams(searchParams);
    for (const [name, value] of Object.entries(updates)) {
      if (value) next.set(name, value);
      else next.delete(name);
    }
    if (resetPage) next.delete("page");
    setSearchParams(next);
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    updateSearchParams({ q: searchDraft.trim() || undefined }, true);
  }

  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasFilters = Boolean(q || group || sort !== "name-asc");

  return (
    <main id="main" className="directory-page">
      <span className="eyebrow">Explore</span>
      <h1 className="page-title" tabIndex={-1}>Species directory</h1>
      <p className="page-lead">
        Search the public demonstration catalogue, then open a species to explore its map,
        yearly pattern and accessible records.
      </p>

      <form className="directory-controls" role="search" aria-label="Filter the species directory" onSubmit={submitSearch}>
        <div className="control-field directory-search">
          <label htmlFor="species-search">Search by common or scientific name</label>
          <div className="search-row">
            <input
              id="species-search"
              type="search"
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              autoComplete="off"
            />
            <button className="btn" type="submit">Search</button>
          </div>
        </div>

        <div className="control-field">
          <label htmlFor="species-group">Group</label>
          <select
            id="species-group"
            value={group}
            onChange={(event) => updateSearchParams({ group: event.target.value || undefined }, true)}
          >
            <option value="">All groups</option>
            {groups.map((facet) => (
              <option key={facet.value} value={facet.value}>
                {facet.label} ({facet.speciesCount})
              </option>
            ))}
          </select>
        </div>

        <div className="control-field">
          <label htmlFor="species-sort">Sort</label>
          <select
            id="species-sort"
            value={sort}
            onChange={(event) => updateSearchParams({ sort: event.target.value }, true)}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </div>

        {hasFilters ? (
          <button
            className="btn-ghost directory-clear"
            type="button"
            onClick={() => {
              setSearchDraft("");
              setSearchParams({});
            }}
          >
            Clear filters
          </button>
        ) : null}
      </form>

      <section className="directory-results" aria-labelledby="species-results-heading" aria-busy={query.isFetching}>
        <div className="directory-results__head">
          <div>
            <h2 id="species-results-heading">Species</h2>
            <p className="results-summary" aria-live="polite">
              {query.data
                ? `${query.data.total.toLocaleString("en-GB")} ${query.data.total === 1 ? "species" : "species"} found`
                : "Loading species count"}
            </p>
          </div>
          {query.isFetching && !query.isPending ? <p role="status">Updating results…</p> : null}
        </div>

        {state.status === "loading" ? (
          <div className="state"><LoadingState label="species" /></div>
        ) : state.status === "error" ? (
          <div className="directory-state">
            <ErrorState message={state.error.message} onRetry={() => void query.refetch()} />
          </div>
        ) : state.status === "empty" ? (
          <div className="directory-state">
            <EmptyState message={total > 0 ? "No species are listed on this page." : "No species match your filters."} />
          </div>
        ) : (
          <ul className="species-grid">
            {state.data.items.map((species) => {
              const name = species.commonName ?? species.scientificName;
              const groupLabel = state.data.facets.groups.find((facet) => facet.value === species.group)?.label ?? species.group;
              return (
                <li className="species-card" key={species.speciesId}>
                  <div>
                    <span className="species-card__group">{groupLabel}</span>
                    <h3>{name}</h3>
                    {species.commonName ? <p className="species-card__scientific">{species.scientificName}</p> : null}
                  </div>
                  <dl className="species-card__facts">
                    <div><dt>Records</dt><dd>{species.recordCount.toLocaleString("en-GB")}</dd></div>
                    <div>
                      <dt>Years</dt>
                      <dd>{species.firstYear === null || species.lastYear === null ? "No records" : `${species.firstYear}–${species.lastYear}`}</dd>
                    </div>
                  </dl>
                  <Link className="species-card__link" href={`/species/${encodeURIComponent(species.speciesId)}/${species.slug}`}>
                    Explore {name}<span aria-hidden="true"> →</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}

        {query.data && query.data.total > 0 ? (
          <nav className="pagination" aria-label="Species results pages">
            <button
              type="button"
              className="btn-ghost"
              disabled={page <= 1}
              onClick={() => updateSearchParams({ page: String(page - 1) })}
            >
              Previous
            </button>
            <span>Page {page} of {totalPages}</span>
            <button
              type="button"
              className="btn-ghost"
              disabled={page >= totalPages}
              onClick={() => updateSearchParams({ page: String(page + 1) })}
            >
              Next
            </button>
          </nav>
        ) : null}
      </section>
    </main>
  );
}
