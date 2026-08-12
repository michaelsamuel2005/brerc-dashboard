import { toAsyncState, useRecords } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";

// Published individual records for one species. The response carries the approved
// publication mode and field capabilities, so an aggregates-only policy cannot be
// mistaken for a species with zero records.
export function RecordsTable({ speciesId, year = null }: { speciesId: string; year?: number | null }) {
  const query = useRecords({ species: speciesId, year: year ?? undefined });
  const state = toAsyncState(query);

  if (state.status === "ready" && state.data.publication.mode === "aggregates-only") {
    return (
      <section className="table-section" aria-labelledby="records-heading">
        <h2 id="records-heading">Individual records</h2>
        <p className="map-note">
          Individual records are not published. The distribution-by-grid-square table above
          provides the accessible aggregate view.
        </p>
      </section>
    );
  }

  const heading = state.status === "ready" ? "Published records" : "Individual records";

  return (
    <section className="table-section" aria-labelledby="records-heading">
      <h2 id="records-heading">{heading}</h2>
      <p className="map-note">
        {state.status === "ready"
          ? `Showing ${state.data.items.length.toLocaleString("en-GB")} of ${state.data.total.toLocaleString("en-GB")} published individual records for this species.`
          : "Loading the individual-record publication status."}
      </p>
      {state.status === "loading" ? (
        <div className="state"><LoadingState label="records" /></div>
      ) : state.status === "error" ? (
        <ErrorState message={state.error.message} onRetry={() => void query.refetch()} />
      ) : state.status === "empty" ? (
        <EmptyState message="No published individual records match this view." />
      ) : state.data.items.length === 0 ? (
        <EmptyState
          message={
            year === null
              ? "No individual records are published for this species."
              : `No individual records are published for ${year}.`
          }
        />
      ) : (
        <div className="tablewrap">
          <div
            className="tscroll"
            tabIndex={0}
            role="group"
            aria-label="Published individual records, scrollable"
            data-a11y-non-pointer-target
          >
            <table className="data">
              <caption>
                Published individual records at their approved public capture resolution — no
                exact coordinates or personal data. Only fields enabled by the publication policy
                are shown.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Species</th>
                  <th scope="col">Grid reference</th>
                  <th scope="col">Capture resolution</th>
                  <th scope="col" className="num">Year</th>
                  {state.data.publication.fields.place ? <th scope="col">Place</th> : null}
                  {state.data.publication.fields.abundance ? <th scope="col">Abundance</th> : null}
                  {state.data.publication.fields.recordType ? <th scope="col">Record type</th> : null}
                  {state.data.publication.fields.verification ? <th scope="col">Verified</th> : null}
                </tr>
              </thead>
              <tbody>
                {state.data.items.map((r) => (
                  <tr key={r.id}>
                    <td>{r.commonName ?? r.scientificName}</td>
                    <td>{r.gridRef}</td>
                    <td>{precisionLabel(r.precisionMetres)}</td>
                    <td className="num">{r.year}</td>
                    {state.data.publication.fields.place ? <td>{r.place ?? "—"}</td> : null}
                    {state.data.publication.fields.abundance ? <td>{r.abundance ?? "—"}</td> : null}
                    {state.data.publication.fields.recordType ? <td>{r.recordType ?? "—"}</td> : null}
                    {state.data.publication.fields.verification ? (
                      <td style={{ textTransform: "capitalize" }}>{r.verified}</td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
