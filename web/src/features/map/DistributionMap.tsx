import { useCallback } from "react";
import Map, { AttributionControl, Layer, NavigationControl, Source, type MapLayerMouseEvent } from "react-map-gl/maplibre";
import type { FeatureCollection } from "geojson";
import type { FilterSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useState } from "react";
import { toAsyncState, useDistributionCells } from "../../lib/api";
import { gridRefToPolygon } from "../../lib/geo/osgb";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";
import { Legend } from "./Legend";
import { INITIAL_VIEW, MAP_STYLE, MAX_ZOOM, cellsFillLayer, cellsLineLayer } from "./mapConfig";

interface Props {
  speciesId: string;
  selectedCellId?: string | null;
  onSelectCell?: (cellId: string | null) => void;
}

// The species-distribution map (R2), on react-map-gl/maplibre. Cell polygons are DERIVED
// from validated grid IDs (osgb), so server geometry is never trusted. Selection is shared
// with the cell table + the selected-cell card via one authoritative selectedCellId — the
// selected square gets a two-layer (light casing + dark line) halo for reliable contrast.
// No popup and no auto-scroll, so a map click cannot move the page.
export default function DistributionMap({ speciesId, selectedCellId = null, onSelectCell }: Props) {
  const query = useDistributionCells({ species: speciesId });
  const state = toAsyncState(query, (d) => d.cells.length === 0);
  const [mapError, setMapError] = useState<string | null>(null);
  const box = { display: "grid", placeItems: "center" } as const;

  const onClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const f = e.features?.[0];
      onSelectCell?.(f && f.properties ? String(f.properties.cellId) : null);
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

  // Build GeoJSON from the validated cell IDs — geometry cannot be spoofed by the server.
  const fc: FeatureCollection = {
    type: "FeatureCollection",
    features: state.data.cells.flatMap((c) => {
      const ring = gridRefToPolygon(c.cellId);
      if (!ring) return [];
      return [
        {
          type: "Feature" as const,
          geometry: { type: "Polygon" as const, coordinates: [ring] },
          properties: { cellId: c.cellId, recordCount: c.recordCount, precisionMetres: c.precisionMetres },
        },
      ];
    }),
  };

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
        <Source id="cells" type="geojson" data={fc}>
          <Layer {...cellsFillLayer} />
          <Layer {...cellsLineLayer} />
          <Layer id="cells-highlight-casing" type="line" filter={highlightFilter} paint={{ "line-color": "#ffffff", "line-width": 6, "line-opacity": 0.95 }} />
          <Layer id="cells-highlight" type="line" filter={highlightFilter} paint={{ "line-color": "#0b3b23", "line-width": 2.5 }} />
        </Source>
      </Map>
      <Legend />
    </div>
  );
}
