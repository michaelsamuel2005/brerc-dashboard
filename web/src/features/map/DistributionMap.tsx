import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { toAsyncState, useDistributionCells } from "../../lib/api";
import { precisionLabel } from "../../lib/geo/gridref";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";
import type { CellCollection } from "../../lib/api/schemas";
import { Legend } from "./Legend";
import { CELLS_SOURCE_ID, INITIAL_VIEW, MAP_STYLE, MAX_ZOOM, cellsFillLayer, cellsLineLayer } from "./mapConfig";

// The species-distribution map (R2). Honest grid cells at their true precision — never
// false-precision pins. Its accessible equivalent is the records table below it.
export default function DistributionMap() {
  const query = useDistributionCells();
  const state = toAsyncState(query, (d) => d.features.length === 0);
  const boxed = { display: "grid", placeItems: "center" } as const;

  if (state.status === "loading")
    return <div className="map-card" style={boxed}><LoadingState label="the map" /></div>;
  if (state.status === "error")
    return <div className="map-card" style={boxed}><ErrorState message={state.error.message} onRetry={() => void query.refetch()} /></div>;
  if (state.status === "empty")
    return <div className="map-card" style={boxed}><EmptyState message="No mapped records for this species yet." /></div>;

  return (
    <div className="map-card">
      <MapCanvas cells={state.data} />
      <Legend />
    </div>
  );
}

function MapCanvas({ cells }: { cells: CellCollection }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  // Create the map exactly once. All imperative MapLibre calls are isolated here.
  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current) return;
    const map = new maplibregl.Map({
      container,
      style: MAP_STYLE,
      center: [INITIAL_VIEW.longitude, INITIAL_VIEW.latitude],
      zoom: INITIAL_VIEW.zoom,
      maxZoom: MAX_ZOOM,
      cooperativeGestures: true,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      map.addSource(CELLS_SOURCE_ID, { type: "geojson", data: cells });
      map.addLayer(cellsFillLayer);
      map.addLayer(cellsLineLayer);
      map.on("mouseenter", "cells-fill", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "cells-fill", () => (map.getCanvas().style.cursor = ""));
      map.on("click", "cells-fill", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties as { cellId: string; recordCount: number; precisionMetres: number };
        new maplibregl.Popup({ closeButton: false, offset: 8 })
          .setLngLat(e.lngLat)
          .setHTML(
            `<div style="font-family:Inter,sans-serif;font-size:.85rem"><b>${p.cellId}</b><br>${p.recordCount} records &middot; ${precisionLabel(p.precisionMetres)}</div>`,
          )
          .addTo(map);
      });
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // Create-once: subsequent data changes are handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push new cell data when it changes (e.g. switching species in later phases).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      const src = map.getSource(CELLS_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
      src?.setData(cells);
    };
    if (map.isStyleLoaded() && map.getSource(CELLS_SOURCE_ID)) apply();
    else map.once("load", apply);
  }, [cells]);

  return (
    <div
      ref={containerRef}
      id="map"
      role="region"
      aria-label="Species distribution map of the West of England. The same data is available in the accessible table below."
    />
  );
}
