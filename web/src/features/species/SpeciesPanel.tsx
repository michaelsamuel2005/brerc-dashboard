import { toAsyncState, useSpeciesDetail } from "../../lib/api";
import { AttributedImage } from "../../components/AttributedImage";
import { ErrorState, LoadingState } from "../../components/states/States";

// Species info panel (R3): name, description, an attributed/licensed image, and honest
// summary statistics — driven by the typed useSpeciesDetail hook.
export function SpeciesPanel({ speciesId }: { speciesId: string }) {
  const query = useSpeciesDetail(speciesId);
  const state = toAsyncState(query);

  if (state.status === "loading")
    return <div className="panel"><div className="panel-body"><LoadingState label="species information" /></div></div>;
  if (state.status === "error")
    return <div className="panel"><div className="panel-body"><ErrorState message={state.error.message} onRetry={() => void query.refetch()} /></div></div>;
  if (state.status === "empty") return null;

  const s = state.data;
  const name = s.commonName ?? s.scientificName;
  return (
    <article className="panel species-panel" aria-labelledby="species-heading">
      <AttributedImage image={s.image} name={name} />
      <div className="panel-body">
        <h2 id="species-heading">
          {name}
          <span className="chip">{s.group}</span>
        </h2>
        <p className="sci">{s.scientificName}</p>
        {s.description ? <p className="desc">{s.description}</p> : null}
        <div className="stats">
          <div className="stat">
            <div className="v">{s.stats.recordCount.toLocaleString("en-GB")}</div>
            <div className="k">Records</div>
          </div>
          <div className="stat">
            <div className="v">
              {s.stats.yearRange[0]}–{s.stats.yearRange[1]}
            </div>
            <div className="k">Years</div>
          </div>
          <div className="stat">
            <div className="v">{s.stats.verifiedCount.toLocaleString("en-GB")}</div>
            <div className="k">Verified</div>
          </div>
        </div>
      </div>
    </article>
  );
}
