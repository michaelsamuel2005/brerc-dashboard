import { type FormEvent, useState } from "react";
import { Link, useLocation } from "wouter";
import { ErrorState, LoadingState } from "../../components/states/States";
import { toAsyncState, useProvenance, useSpeciesList, useSummary } from "../../lib/api";
import { YearBars } from "./YearBars";

const FEATURED_COUNT = 4;

function formatNumber(value: number): string {
  return value.toLocaleString("en-GB");
}

/** ISO timestamp -> a date a reader recognises. Falls back to the raw string. */
function formatDate(iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime())
    ? iso
    : parsed.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

/**
 * When the data was last refreshed, and who holds it.
 *
 * Uses /api/meta/provenance, which the API has served since the canonical port with
 * nothing rendering it — the update date was being published and thrown away. Only the
 * date and the holder are shown; see the comment inside for what was taken out after
 * client meeting 2 and why.
 */
function ProvenanceStrip() {
  const state = toAsyncState(useProvenance());
  if (state.status !== "ready") return null;
  const { lastUpdated } = state.data;

  // Deliberately short. BRERC were confused by the data-source section at client meeting
  // 2 — "the only data source is BRERC" — so the list of source labels is gone; a
  // multi-source line described a data model they do not have.
  //
  // The generalisation tiers are gone from here too. BRERC asked for the explanation of
  // how sensitive locations are blurred to be removed, and a coarsest-tier figure in
  // metres IS that explanation, stated numerically. What stays is on the squares
  // themselves, where each one gives its own capture resolution: that is what the square
  // means, not how it was produced.
  return (
    <p className="provenance-strip">
      <span className="dot" aria-hidden="true" />
      <span>Records held by <strong>BRERC</strong></span>
      <span>Last updated <strong>{formatDate(lastUpdated)}</strong></span>
      <Link href="/about">How to read this</Link>
    </p>
  );
}

/**
 * Records by taxonomic group.
 *
 * The prototype drew this chart from invented totals. The real release cannot yet fill
 * it: `taxon_group` is CHECK-constrained NULL in the publication store because BRERC has
 * not approved a group vocabulary, so /api/summary correctly returns an empty list. The
 * honest response is to say so, not to substitute numbers — a chart of made-up
 * proportions on a public dashboard is worse than no chart.
 */
export function GroupBreakdown({ groups }: { groups: readonly { group: string; count: number }[] }) {
  if (groups.length === 0) {
    return (
      <div className="unavailable">
        <strong>Not available in this release.</strong> Records are not yet grouped by
        taxonomic group in the published data — BRERC has still to approve the vocabulary
        that decides which group each species belongs to. Rather than show a breakdown
        built on a guess, this panel stays empty until that list exists.
      </div>
    );
  }
  // A release can legitimately publish a group that has no records in it yet, and a
  // release where every group is empty makes both of these zero. Dividing by them would
  // print "NaN%" on the public overview.
  const max = Math.max(...groups.map((g) => g.count));
  const total = groups.reduce((sum, g) => sum + g.count, 0);
  return (
    <dl className="hbars">
      {groups.map((g) => (
        <div className="hbar-row" key={g.group}>
          <dt>{g.group}</dt>
          <dd className="hbar-track">
            <div className="hbar-fill" style={{ width: max > 0 ? `${(g.count / max) * 100}%` : "0%" }} />
          </dd>
          {/* The number is always present as text: the bar is an illustration of it,
              never the only way to read the value (WCAG 1.4.1). The share is omitted
              rather than shown as 0% when there is no total to take a share of. */}
          <dd className="hbar-value">
            {formatNumber(g.count)}
            {total > 0 ? ` · ${((g.count / total) * 100).toFixed(1)}%` : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function FeaturedSpecies() {
  const query = useSpeciesList({ sort: "records-desc", page: 1, pageSize: FEATURED_COUNT });
  const state = toAsyncState(query, (data) => data.items.length === 0);
  if (state.status === "loading") return <div className="state"><LoadingState label="featured species" /></div>;
  if (state.status === "error") return <div className="state"><ErrorState message={state.error.message} onRetry={() => void query.refetch()} /></div>;
  if (state.status === "empty") return null;

  return (
    <ul className="featured">
      {state.data.items.map((species) => {
        const name = species.commonName ?? species.scientificName;
        return (
          <li className="feature-card" key={species.speciesId}>
            {/* Decorative band, not an image slot: a photograph must carry a verified
                licence and attribution, and inventing one here would breach that rule. */}
            <div className="band" aria-hidden="true" />
            <div className="body">
              <h3>{name}</h3>
              {species.commonName ? <p className="sci">{species.scientificName}</p> : null}
              <p className="facts">
                {formatNumber(species.recordCount)} records
                {species.firstYear !== null && species.lastYear !== null
                  ? ` · ${species.firstYear}–${species.lastYear}`
                  : null}
              </p>
              <Link className="btn-ghost" href={`/species/${encodeURIComponent(species.speciesId)}/${species.slug}`}>
                Explore {name}
              </Link>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function OverviewPage() {
  const [, navigate] = useLocation();
  const [search, setSearch] = useState("");
  const query = useSummary();
  const state = toAsyncState(query);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const term = search.trim();
    navigate(term ? `/species?q=${encodeURIComponent(term)}` : "/species");
  }

  const summary = state.status === "ready" ? state.data : null;
  const years = summary?.recordsByYear ?? [];
  const peak = years.reduce<{ year: number; count: number } | null>(
    (best, entry) => (best === null || entry.count > best.count ? entry : best),
    null,
  );

  return (
    <main id="main">
      <section className="hero" aria-labelledby="overview-heading">
        <span className="hero-places">
          Bristol · Bath &amp; NE Somerset · North Somerset · South Gloucestershire
        </span>
        <h1 className="page-title" id="overview-heading" tabIndex={-1}>
          The living record of the West of England
        </h1>
        <p>
          {/* The count comes from the release, never from a figure typed here. BRERC put
              their catalogue at 15,000-16,000 species, but this page must describe what
              is actually published — writing that number in would state something the
              current release does not support, which is the habit this whole review was
              about. */}
          {summary
            ? `Search ${formatNumber(summary.totalSpecies)} ${summary.totalSpecies === 1 ? "species" : "species"} and see where each has been recorded across the region, square by square, at the resolution the records actually support.`
            : "Search the region's species and see where each has been recorded, square by square, at the resolution the records actually support."}
        </p>
        <form className="herosearch" role="search" aria-label="Search species" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="overview-search">
            Search by common or scientific name
          </label>
          <input
            id="overview-search"
            type="search"
            placeholder="Search a species…"
            autoComplete="off"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <button className="btn" type="submit">Search</button>
        </form>
      </section>

      <ProvenanceStrip />

      {state.status === "error" ? (
        <div className="directory-state">
          <ErrorState message={state.error.message} onRetry={() => void query.refetch()} />
        </div>
      ) : (
        <>
          <div className="kpis">
            <div className="kpi">
              <div className="v">{summary ? formatNumber(summary.totalRecords) : "—"}</div>
              <div className="k">Records published</div>
            </div>
            <div className="kpi">
              <div className="v">{summary ? formatNumber(summary.totalSpecies) : "—"}</div>
              <div className="k">Species</div>
            </div>
            <div className="kpi">
              <div className="v">
                {summary?.yearRange ? `${summary.yearRange.min}–${summary.yearRange.max}` : "—"}
              </div>
              <div className="k">Years covered</div>
            </div>
            <div className="kpi">
              <div className="v">{peak ? formatNumber(peak.count) : "—"}</div>
              <div className="k">Busiest year</div>
              {peak ? <div className="n">{peak.year}</div> : null}
            </div>
          </div>

          <div className="grid-2">
            <section className="chart-card" aria-labelledby="effort-heading">
              <div className="section-head">
                <h2 id="effort-heading">Recording effort over time</h2>
                <span className="aside">records per year</span>
              </div>
              {state.status === "loading" ? (
                <LoadingState label="the yearly totals" />
              ) : years.length === 0 ? (
                <div className="unavailable">This release publishes no yearly totals.</div>
              ) : (
                <>
                  <YearBars
                    data={years}
                    label={`Bar chart of records submitted per year, ${years[0]?.year} to ${years[years.length - 1]?.year}.${
                      peak ? ` The highest year is ${peak.year} with ${formatNumber(peak.count)} records.` : ""
                    } The same figures are in the table below.`}
                  />
                  <p className="map-note">
                    {summary?.coverageCaveat} Years count when a record was{" "}
                    <em>made</em>, not when BRERC received it — a batch of older records
                    added recently raises the earlier year it belongs to, not this one.
                  </p>
                  <details className="chart-table">
                    <summary>Yearly figures as a table ({years.length} years)</summary>
                    <div className="tscroll" tabIndex={0} role="group" aria-label="Records by year, scrollable">
                      <table className="data">
                        <caption>Records submitted per year. Counts show recording effort, not abundance.</caption>
                        <thead>
                          <tr>
                            <th scope="col">Year</th>
                            <th scope="col" className="num">Records</th>
                          </tr>
                        </thead>
                        <tbody>
                          {years.map((entry) => (
                            <tr key={entry.year}>
                              <th scope="row">{entry.year}</th>
                              <td className="num">{formatNumber(entry.count)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                </>
              )}
            </section>

            <section className="chart-card" aria-labelledby="groups-heading">
              <div className="section-head">
                <h2 id="groups-heading">Records by group</h2>
              </div>
              {state.status === "loading" ? (
                <LoadingState label="the group breakdown" />
              ) : (
                <GroupBreakdown groups={summary?.topGroups ?? []} />
              )}
            </section>
          </div>

          <section aria-labelledby="featured-heading" style={{ marginTop: "var(--sp-3)" }}>
            <div className="section-head">
              <h2 id="featured-heading">Most recorded species</h2>
              <Link className="btn-ghost" href="/species">Browse all species</Link>
            </div>
            <FeaturedSpecies />
          </section>
        </>
      )}
    </main>
  );
}
