import { useCallback, useState } from "react";
import Map, { AttributionControl, Layer, NavigationControl, Popup, Source, type MapLayerMouseEvent } from "react-map-gl/maplibre";
import type { FeatureCollection } from "geojson";
import type { FilterSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { toAsyncState, useDistributionCells } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";
import { Legend } from "./Legend";
import { INITIAL_VIEW, MAP_STYLE, MAX_ZOOM, cellsFillLayer, cellsLineLayer } from "./mapConfig";

interface PopupInfo {
  longitude: number;
  latitude: number;
  cellId: string;
  recordCount: number;
  precisionMetres: number;
}

interface Props {
  speciesId: string;
  selectedCellId?: string | null;
  onSelectCell?: (cellId: string | null) => void;
}

// The species-distribution map (R2), on react-map-gl/maplibre per the brief. Honest grid
// cells at their true 1 km extent — never pins. Selection is shared with the cell table:
// clicking a square selects it; the selected square gets a bright outline. The popup
// renders React children (no innerHTML), so API strings cannot inject markup.
export default function DistributionMap({ speciesId, selectedCellId = null, onSelectCell }: Props) {
  const query = useDistributionCells({ species: speciesId });
  const state = toAsyncState(query, (d) => d.features.length === 0);
  const [popup, setPopup] = useState<PopupInfo | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const box = { display: "grid", placeItems: "center" } as const;

  const onClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const f = e.features?.[0];
      if (!f || !f.properties) {
        setPopup(null);
        onSelectCell?.(null);
        return;
      }
      const p = f.properties as { cellId: string; recordCount: number; precisionMetres: number };
      setPopup({
        longitude: e.lngLat.lng,
        latitude: e.lngLat.lat,
        cellId: String(p.cellId),
        recordCount: Number(p.recordCount),
        precisionMetres: Number(p.precisionMetres),
      });
      onSelectCell?.(String(p.cellId));
    },
    [onSelectCell],
  );

  if (state.status === "loading") return <div className="map-card" style={box}><LoadingState label="the map" /></div>;
  if (state.status === "error") return <div className="map-card" style={box}><ErrorState message={state.error.message} onRetry={() => void query.refetch()} /></div>;
  if (state.status === "empty") return <div className="map-card" style={box}><EmptyState message="No mapped records for this species yet." /></div>;

  if (mapError) {
    return (
      <div className="map-card" style={box}>
        <p className="state" role="alert">
          The map couldn’t load ({mapError}). The grid-square table below has the same information.
        </p>
      </div>
    );
  }

  const highlightFilter: FilterSpecification = ["==", ["get", "cellId"], selectedCellId ?? "__none__"];

  return (
    <div className="map-card">
      <Map
        initialViewState={INITIAL_VIEW}
        mapStyle={MAP_STYLE}
        maxZoom={MAX_ZOOM}
        interactiveLayerIds={["cells-fill"]}
        onClick={onClick}
        onError={(e) => setMapError(e.error?.message ?? "unknown error")}
        cooperativeGestures
        attributionControl={false}
        style={{ position: "absolute", inset: 0 }}
      >
        <NavigationControl position="bottom-right" showCompass={false} />
        <AttributionControl compact position="bottom-left" />
        <Source id="cells" type="geojson" data={state.data as unknown as FeatureCollection}>
          <Layer {...cellsFillLayer} />
          <Layer {...cellsLineLayer} />
          <Layer id="cells-highlight" type="line" filter={highlightFilter} paint={{ "line-color": "#c0632b", "line-width": 3 }} />
        </Source>
        {popup ? (
          <Popup
            longitude={popup.longitude}
            latitude={popup.latitude}
            closeButton={false}
            closeOnClick
            offset={8}
            onClose={() => setPopup(null)}
          >
            <div className="map-popup">
              <strong>{popup.cellId}</strong>
              <br />
              {popup.recordCount} records · {precisionLabel(popup.precisionMetres)}
            </div>
          </Popup>
        ) : null}
      </Map>
      <Legend />
    </div>
  );
}
