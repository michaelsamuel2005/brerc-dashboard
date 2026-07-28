import { useCallback, useState } from "react";
import Map, { AttributionControl, Layer, NavigationControl, Popup, Source, type MapLayerMouseEvent } from "react-map-gl/maplibre";
import type { FeatureCollection } from "geojson";
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

// The species-distribution map (R2), on react-map-gl/maplibre per the brief. Honest grid
// cells at their true 1 km extent — never false-precision pins. The popup renders React
// children (no innerHTML), so API strings cannot inject markup. Its accessible equivalent
// is the grid-square table beneath it.
export default function DistributionMap({ speciesId }: { speciesId: string }) {
  const query = useDistributionCells({ species: speciesId });
  const state = toAsyncState(query, (d) => d.features.length === 0);
  const [popup, setPopup] = useState<PopupInfo | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const box = { display: "grid", placeItems: "center" } as const;

  const onClick = useCallback((e: MapLayerMouseEvent) => {
    const f = e.features?.[0];
    if (!f || !f.properties) {
      setPopup(null);
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
  }, []);

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
