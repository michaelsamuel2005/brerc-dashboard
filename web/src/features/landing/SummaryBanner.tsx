// The headline totals + honest coverage caveat at the top of the landing page (R1, R4).
// Spec: BRERC_Frontend_Working_Doc_Athul.pdf §3.2.
import { useEffect, useState } from "react";
import { toAsyncState, useSummary } from "../../lib/api";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";
import type { Summary } from "../../lib/api/schemas";

export function SummaryBar() {
  const query = useSummary();
  const state = toAsyncState(query, (data) => data.totalRecords === 0);

  if (state.status === "loading") return <LoadingState label="summary" />;
  if (state.status === "error") return <ErrorState message={state.error.message} onRetry={function (): void {
    throw new Error("Function not implemented.");
  } } />;
  if (state.status === "empty") return null;
  const s = state.data;
  return (
    <section className="panel summary-bar" aria-labelledby="summary-heading">
      <div className="panel-body">
        <h2 id="summary-heading">Overview</h2>

        <div className="stats" role="list" aria-label="Headline totals">
          <div className="stat" role="listitem">
            <div className="v">{data.totalRecords.toLocaleString()}</div>
            <div className="k">Records</div>
          </div>
          <div className="stat" role="listitem">
            <div className="v">{data.totalSpecies.toLocaleString()}</div>
            <div className="k">Species</div>
          </div>
          <div className="stat" role="listitem">
            <div className="v">
              {data.yearRange.min}&ndash;{data.yearRange.max}
            </div>
            <div className="k">Years covered</div>
          </div>
        </div>

        {data.topGroups.length > 0 && (
          <div className="summary-groups">
            <h3>Most-recorded groups</h3>
            <ul>
              {data.topGroups.map((g) => (
                <li key={g.group}>
                  <span className="summary-groups-name">{g.group}</span>
                  <span className="summary-groups-count">{g.count.toLocaleString()} records</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Mounted empty, filled in after mount so the update is announced (not silent). */}
        <p className="sr-only" role="status" aria-live="polite">
          {announcement}
        </p>

        <p className="caveat">
          <strong>Please note:</strong> {data.coverageCaveat}
        </p>
      </div>
    </section>
  );
}