import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toAsyncState, useSummary } from "../../lib/api";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";

interface Props {
  speciesId: string;
  selectedYear: number | null;
  onSelectYear: (year: number | null) => void;
}

const BAR = "#3f9e63";
const BAR_SELECTED = "#c0632b";

// Records submitted by year (R1). The drawn chart is a visual presentation (role="img"
// with a summarising label); the EQUIVALENT TABLE below it is the accessible interface —
// every year is a 44px real button. The narrow SVG bars are deliberately presentational:
// making them separate pointer targets would violate the project's 44px rule on phones.
// Counts are recording EFFORT, not abundance.
export default function RecordsByYearChart({ speciesId, selectedYear, onSelectYear }: Props) {
  const query = useSummary({ species: speciesId });
  const state = toAsyncState(query, (d) => d.recordsByYear.length === 0);

  if (state.status === "loading") return <section className="panel"><div className="panel-body"><LoadingState label="the yearly chart" /></div></section>;
  if (state.status === "error")
    return (
      <section className="panel">
        <div className="panel-body">
          <ErrorState message={state.error.message} onRetry={() => void query.refetch()} />
        </div>
      </section>
    );
  if (state.status === "empty") return <section className="panel"><div className="panel-body"><EmptyState message="No yearly totals for this species." /></div></section>;

  const data = state.data.recordsByYear;
  const first = data[0]?.year;
  const last = data[data.length - 1]?.year;
  const peak = data.reduce((best, d) => (d.count > best.count ? d : best), data[0] ?? { year: 0, count: 0 });
  const total = data.reduce((n, d) => n + d.count, 0);
  const summary = `Bar chart of records submitted per year, ${first} to ${last}. ${total} records in total; the highest year is ${peak.year} with ${peak.count}. The same figures are in the table below this chart.`;

  return (
    <section className="chart-section" aria-labelledby="chart-heading">
      <h2 id="chart-heading">Records submitted by year</h2>
      <p className="map-note">
        {state.data.coverageCaveat} Select a year to filter the map and tables.
        {selectedYear !== null ? ` Showing ${selectedYear}.` : " Showing all years."}
      </p>

      <div className="chart-card">
        <div className="chart-plot" role="img" aria-label={summary}>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
              <CartesianGrid stroke="#e4e0d3" vertical={false} />
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: "#5f6d64" }} tickMargin={6} minTickGap={12} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#5f6d64" }} width={32} />
              <Tooltip
                cursor={{ fill: "rgba(31,94,60,.08)" }}
                formatter={(value) => [`${String(value)} records`, "Submitted"]}
                labelFormatter={(label) => `Year ${String(label)}`}
                contentStyle={{ fontSize: ".82rem", borderRadius: 10, border: "1px solid #e4e0d3" }}
              />
              <Bar
                dataKey="count"
                fill={BAR}
                // Bars must NOT depend on animation: users with "reduce motion" (and headless
                // browsers, which report the same) have CSS animations disabled, which left the
                // bars stuck at zero height — an empty chart. Draw them at final size at once.
                isAnimationActive={false}
              >
                {data.map((d) => (
                  <Cell
                    key={d.year}
                    fill={d.year === selectedYear ? BAR_SELECTED : BAR}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <details className="chart-table">
          <summary>Yearly figures as a table ({data.length} years) — select a year here</summary>
          <div
            className="tscroll"
            tabIndex={0}
            role="group"
            aria-label="Records by year, scrollable"
            data-a11y-non-pointer-target
          >
            <table className="data">
              <caption>Records submitted per year. Counts show recording effort, not abundance.</caption>
              <thead>
                <tr>
                  <th scope="col">Year</th>
                  <th scope="col" className="num">Records</th>
                </tr>
              </thead>
              <tbody>
                {data.map((d) => {
                  const sel = d.year === selectedYear;
                  return (
                    <tr key={d.year} className={sel ? "selected" : undefined}>
                      <td>
                        <button
                          type="button"
                          className="cell-select"
                          aria-pressed={sel}
                          data-a11y-same-action={`year-${d.year}`}
                          onClick={() => onSelectYear(sel ? null : d.year)}
                        >
                          {d.year}
                          <span className="visually-hidden"> — {sel ? "filtering by this year; activate to show all years" : "filter the map and tables by this year"}</span>
                        </button>
                      </td>
                      <td className="num">{d.count.toLocaleString("en-GB")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      </div>
    </section>
  );
}
