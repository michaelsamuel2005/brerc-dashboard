import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "wouter";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";
import { toAsyncState, useDistributionCells, useSpeciesDetail } from "../../lib/api";
import { SpeciesPicker } from "../species/SpeciesPicker";

// Grid-square order and capture resolution only.
//
// There is deliberately no "most records first". BRERC asked for the ranking to go
// (client meeting 2): ordering squares by record count publishes a league table of where
// people have looked, and a reader takes it as a table of where the wildlife is. It is
// the effort bias this whole dashboard warns about, reintroduced as a sort order. The
// count itself stays visible — their objection was to the ranking, and the record-count
// display was one of the things they liked.
const SORTS = ["grid-asc", "resolution-asc"] as const;
type Sort = (typeof SORTS)[number];

const SORT_LABELS: Record<Sort, string> = {
  "grid-asc": "Grid square (A–Z)",
  "resolution-asc": "Capture resolution (finest first)",
};

function readSort(raw: string | null): Sort {
  return (SORTS as readonly string[]).includes(raw ?? "") ? (raw as Sort) : "grid-asc";
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
 * The same table sits under the map on a species page. It gets its own route because it
 * is the accessible equivalent of the map, and an equivalent reachable only by first
 * loading the thing it replaces is not much of an alternative: this page needs no WebGL,
 * no map tiles and no pointer.
 *
 * No download. BRERC do not want people exporting from the dashboard (client meeting 2);
 * data requests go through their own process, which is how licensing and attribution stay
 * attached to the data. The export button, its handler and the CSV module are deleted
 * rather than hidden — an unused export path is what gets switched back on later by
 * someone who was not in that meeting.
 */
export function RecordsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const speciesId = searchParams.get("species") ?? "";
  const filter = searchParams.get("cell") ?? "";
  const sort = readSort(searchParams.get("sort"));
  const [filterDraft, setFilterDraft] = useState(filter);

  useEffect(() => setFilterDraft(filter), [filter]);

  // Resolve the chosen species by id. At 16,000 species the page cannot hold the
  // catalogue to look a name up in, so it asks for the one it needs.
  const detailQuery = useSpeciesDetail(speciesId || undefined);
  const detail = detailQuery.data ?? null;
  const activeName = detail ? (detail.commonName ?? detail.scientificName) : "";

  const cellsQuery = useDistributionCells(speciesId ? { species: speciesId } : undefined);
  const cellsState = toAsyncState(cellsQuery, (data) => data.cells.length === 0);

  const rows = useMemo(() => {
    if (cellsState.status !== "ready") return [];
    const needle = filter.trim().toUpperCase();
    const matched = cellsState.data.cells.filter((cell) =>
      needle ? cell.cellId.toUpperCase().includes(needle) : true,
    );
    const ordered = [...matched];
    ordered.sort((a, b) =>
      sort === "resolution-asc"
        ? a.precisionMetres - b.precisionMetres || a.cellId.localeCompare(b.cellId)
        : a.cellId.localeCompare(b.cellId),
    );
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

  const total = rows.reduce((sum, row) => sum + row.recordCount, 0);

  return (
    <main id="main" className="directory-page">
      <span className="eyebrow">Accessible view</span>
      <h1 className="page-title" tabIndex={-1}>Grid-square summary</h1>
      <p className="page-lead">
        The map&rsquo;s data as a table — every square where a species has been recorded,
        with its record count and the resolution it was captured at. This page needs no
        map: it is the accessible equivalent, not a supplement to it.
      </p>

      <div className="records-layout">
        <section className="panel records-picker" aria-labelledby="records-picker-heading">
          <div className="panel-body">
            <h2 id="records-picker-heading">Choose a species</h2>
            <SpeciesPicker
              idPrefix="records"
              label="Search species"
              selectedId={speciesId || null}
              onSelect={(id) => update({ species: id, cell: undefined })}
            />
          </div>
        </section>

        <div>
          {!speciesId ? (
            <div className="directory-state">
              <EmptyState message="Choose a species to see the squares it has been recorded in." />
            </div>
          ) : (
            <>
              <div className="filter-bar filter-bar--narrow">
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
                  <label htmlFor="records-sort">Order by</label>
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
              </div>

              <p className="result-count" aria-live="polite">
                {cellsState.status === "ready"
                  ? `${formatNumber(rows.length)} ${rows.length === 1 ? "square" : "squares"}, ${formatNumber(total)} records${filter ? ` matching “${filter}”` : ""}`
                  : "Loading grid squares"}
              </p>

              {cellsState.status === "loading" ? (
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
                        Every square {activeName ? `${activeName} has` : "this species has"} been
                        recorded in, listed by grid reference. Each row states its own capture
                        resolution. Counts show how much recording has happened in a square, not
                        how much wildlife is there.
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

              {detail ? (
                <p className="map-note">
                  <Link href={`/species/${encodeURIComponent(detail.speciesId)}/${detail.slug}`}>
                    See {activeName} on the map →
                  </Link>
                </p>
              ) : null}
            </>
          )}
        </div>
      </div>
    </main>
  );
}
