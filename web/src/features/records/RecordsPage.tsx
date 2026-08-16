import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "wouter";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";
import { toAsyncState, useDistributionCells, useSpeciesList } from "../../lib/api";
import { MAX_PAGE_SIZE } from "../../lib/api/schemas";
import { csvFilename, toCsv } from "./csv";

const SORTS = ["records-desc", "grid-asc", "resolution-asc"] as const;
type Sort = (typeof SORTS)[number];

const SORT_LABELS: Record<Sort, string> = {
  "records-desc": "Records (most first)",
  "grid-asc": "Grid square (A–Z)",
  "resolution-asc": "Capture resolution (finest first)",
};

function readSort(raw: string | null): Sort {
  return (SORTS as readonly string[]).includes(raw ?? "") ? (raw as Sort) : "records-desc";
}

function formatNumber(value: number): string {
  return value.toLocaleString("en-GB");
}

function describeResolution(metres: number): string {
  return metres >= 1000 ? `${metres / 1000} km square` : `${metres} m square`;
}

/**
 * The grid-square summary as a page of its own.
 *
 * The same table already sits under the map on a species page. It gets its own route
 * because it is the accessible equivalent of the map, and an equivalent that can only be
 * reached by first loading the thing it is an alternative to is not much of an
 * alternative: this page needs no WebGL, no map tiles and no pointer.
 */
export function RecordsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const speciesId = searchParams.get("species") ?? "";
  const filter = searchParams.get("cell") ?? "";
  const sort = readSort(searchParams.get("sort"));
  const [filterDraft, setFilterDraft] = useState(filter);

  useEffect(() => setFilterDraft(filter), [filter]);

  // The picker needs every species, not a page of them; the API caps page size, so ask
  // for the maximum and say so if it truncates rather than silently offering a subset.
  const speciesQuery = useSpeciesList({ sort: "name-asc", page: 1, pageSize: MAX_PAGE_SIZE });
  const speciesState = toAsyncState(speciesQuery);
  const options = speciesState.status === "ready" ? speciesState.data.items : [];
  const truncated = speciesState.status === "ready" && speciesState.data.total > options.length;

  // Default to the first species once the list arrives, so the page is never an empty
  // frame waiting for a choice the visitor has no way to guess.
  const activeId = speciesId || options[0]?.speciesId || "";
  const active = options.find((item) => item.speciesId === activeId) ?? null;
  const activeName = active ? (active.commonName ?? active.scientificName) : "";

  const cellsQuery = useDistributionCells(activeId ? { species: activeId } : undefined);
  const cellsState = toAsyncState(cellsQuery, (data) => data.cells.length === 0);

  const rows = useMemo(() => {
    if (cellsState.status !== "ready") return [];
    const needle = filter.trim().toUpperCase();
    const matched = cellsState.data.cells.filter((cell) =>
      needle ? cell.cellId.toUpperCase().includes(needle) : true,
    );
    const ordered = [...matched];
    ordered.sort((a, b) => {
      if (sort === "grid-asc") return a.cellId.localeCompare(b.cellId);
      if (sort === "resolution-asc") return a.precisionMetres - b.precisionMetres || a.cellId.localeCompare(b.cellId);
      return b.recordCount - a.recordCount || a.cellId.localeCompare(b.cellId);
    });
    return ordered;
  }, [cellsState, filter, sort]);

  const verificationAvailable =
    cellsState.status === "ready" ? cellsState.data.verificationAvailable : false;

  function update(changes: Readonly<Record<string, string | undefined>>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setSearchParams(next);
  }

  function download() {
    const csv = toCsv(
      rows.map((row) => ({
        cellId: row.cellId,
        precisionMetres: row.precisionMetres,
        recordCount: row.recordCount,
        verifiedCount: verificationAvailable ? (row.verifiedCount ?? null) : null,
      })),
      {
        speciesName: activeName,
        verificationAvailable,
        retrieved: new Date().toISOString().slice(0, 10),
      },
    );
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = csvFilename(activeName);
    link.click();
    URL.revokeObjectURL(url);
  }

  const total = rows.reduce((sum, row) => sum + row.recordCount, 0);

  return (
    <main id="main" className="directory-page">
      <span className="eyebrow">Accessible view</span>
      <h1 className="page-title" tabIndex={-1}>Grid-square summary</h1>
      <p className="page-lead">
        The map&rsquo;s data as a table — every occupied square for one species, with its
        record count and the resolution it was captured at. This page needs no map: it is
        the accessible equivalent, not a supplement to it.
      </p>

      <div className="filter-bar">
        <div className="control-field">
          <label htmlFor="records-species">Species</label>
          <select
            id="records-species"
            value={activeId}
            onChange={(event) => update({ species: event.target.value, cell: undefined })}
            disabled={options.length === 0}
          >
            {options.map((item) => (
              <option key={item.speciesId} value={item.speciesId}>
                {item.commonName ?? item.scientificName}
              </option>
            ))}
          </select>
        </div>

        <form
          className="control-field"
          role="search"
          aria-label="Filter grid squares"
          onSubmit={(event) => {
            event.preventDefault();
            update({ cell: filterDraft.trim() || undefined });
          }}
        >
          <label htmlFor="records-cell">Find a grid square</label>
          <div className="search-row">
            <input
              id="records-cell"
              type="search"
              placeholder="e.g. ST58"
              autoComplete="off"
              value={filterDraft}
              onChange={(event) => setFilterDraft(event.target.value)}
            />
            <button className="btn" type="submit">Find</button>
          </div>
        </form>

        <div className="control-field">
          <label htmlFor="records-sort">Sort</label>
          <select
            id="records-sort"
            value={sort}
            onChange={(event) => update({ sort: event.target.value })}
          >
            {SORTS.map((option) => (
              <option key={option} value={option}>{SORT_LABELS[option]}</option>
            ))}
          </select>
        </div>

        <button
          className="btn-ghost"
          type="button"
          onClick={download}
          disabled={rows.length === 0}
        >
          Download CSV
        </button>
      </div>

      {truncated ? (
        <p className="result-count">
          Showing the first {options.length} species by name. Use the{" "}
          <Link href="/species">species directory</Link> to search the full list.
        </p>
      ) : null}

      <p className="result-count" aria-live="polite">
        {cellsState.status === "ready"
          ? `${formatNumber(rows.length)} ${rows.length === 1 ? "square" : "squares"}, ${formatNumber(total)} records${filter ? ` matching “${filter}”` : ""}`
          : "Loading grid squares"}
      </p>

      {speciesState.status === "error" ? (
        <div className="directory-state">
          <ErrorState message={speciesState.error.message} onRetry={() => void speciesQuery.refetch()} />
        </div>
      ) : cellsState.status === "loading" ? (
        <div className="state"><LoadingState label="grid squares" /></div>
      ) : cellsState.status === "error" ? (
        <div className="directory-state">
          <ErrorState message={cellsState.error.message} onRetry={() => void cellsQuery.refetch()} />
        </div>
      ) : cellsState.status === "empty" ? (
        <div className="directory-state">
          <EmptyState message="No mapped records for this species yet." />
        </div>
      ) : rows.length === 0 ? (
        <div className="directory-state">
          <EmptyState message={`No grid square matches “${filter}”.`} />
        </div>
      ) : (
        <div className="tablewrap">
          <div className="tscroll" tabIndex={0} role="group" aria-label="Grid squares, scrollable">
            <table className="data">
              <caption>
                Every published grid square for {activeName}. Each row states its own capture
                resolution; no exact locations are held here or anywhere on this site.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Grid square</th>
                  <th scope="col">Capture resolution</th>
                  <th scope="col" className="num">Records</th>
                  {verificationAvailable ? <th scope="col" className="num">Verified</th> : null}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.cellId}>
                    <th scope="row">{row.cellId}</th>
                    <td>{describeResolution(row.precisionMetres)}</td>
                    <td className="num">{formatNumber(row.recordCount)}</td>
                    {verificationAvailable ? (
                      <td className="num">
                        {row.verifiedCount === null || row.verifiedCount === undefined
                          ? "—"
                          : formatNumber(row.verifiedCount)}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {active ? (
        <p className="map-note">
          <Link href={`/species/${encodeURIComponent(active.speciesId)}/${active.slug}`}>
            See {activeName} on the map →
          </Link>
        </p>
      ) : null}
    </main>
  );
}
