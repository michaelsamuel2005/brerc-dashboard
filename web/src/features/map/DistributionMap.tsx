import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Map, { AttributionControl, Layer, NavigationControl, Source, type MapLayerMouseEvent, type MapRef } from "react-map-gl/maplibre";
import type { FeatureCollection } from "geojson";
import type { FilterSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { toAsyncState, useDistributionCells } from "../../lib/api";
import { gridRefToPolygon } from "../../lib/geo/osgb";
import { circleRing } from "../../lib/geo/radius";
import { usePrefersReducedMotion } from "../../lib/hooks/usePrefersReducedMotion";
import { EmptyState, ErrorState, LoadingState } from "../../components/states/States";
import { Legend } from "./Legend";
import { MapInstructions } from "./MapInstructions";
import { INITIAL_VIEW, MAP_STYLE, MAX_ZOOM, MIN_ZOOM, cellsFillLayer, cellsLineLayer } from "./mapConfig";
import { installA11yTestAdapter, removeA11yTestAdapter } from "./a11yTestAdapter";

interface Props {
  speciesId: string;
  year?: number | null;
  selectedCellId?: string | null;
  onSelectCell?: (cellId: string | null) => void;
  /** Draw the "records near here" query area. The circle is the QUESTION the visitor
   *  asked, never a claim about where a record is — see lib/geo/radius.ts. */
  radius?: { centre: [number, number]; metres: number } | null;
  /** When set, a click anywhere on the map moves the query centre instead of only
   *  selecting a square. */
  onPickCentre?: (centre: [number, number]) => void;
}

type PanDirection = "north" | "south" | "east" | "west";

const PAN_OFFSETS: Readonly<Record<PanDirection, [number, number]>> = {
  north: [0, -120],
  south: [0, 120],
  east: [120, 0],
  west: [-120, 0],
};

const PAN_SYMBOLS: Readonly<Record<PanDirection, string>> = {
  north: "↑",
  south: "↓",
  east: "→",
  west: "←",
};

const PAN_DIRECTIONS = ["north", "west", "east", "south"] as const;
const A11Y_TEST_MODE =
  import.meta.env.DEV && import.meta.env.VITE_A11Y_TEST_MODE === "true";

// The species-distribution map (R2), on react-map-gl/maplibre. Cell polygons are DERIVED
// from validated grid IDs (osgb), so server geometry is never trusted. Selection is shared
// with the cell table + the selected-cell card via one authoritative selectedCellId — the
// selected square gets a two-layer (light casing + dark line) halo for reliable contrast.
// No popup and no auto-scroll, so a map click cannot move the page.
export default function DistributionMap({ speciesId, year = null, selectedCellId = null, onSelectCell, radius = null, onPickCentre }: Props) {
  const query = useDistributionCells({ species: speciesId, year: year ?? undefined });
  const state = toAsyncState(query, (d) => d.cells.length === 0);
  const [mapError, setMapError] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const mapRef = useRef<MapRef | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const box = { display: "grid", placeItems: "center" } as const;
  const readyCells = state.status === "ready" ? state.data.cells : null;

  // Build GeoJSON from validated cell IDs only — geometry supplied by an API can never
  // spoof a more precise location. Memoising also gives the test adapter a stable source.
  const fc = useMemo<FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: readyCells
      ? readyCells.flatMap((cell) => {
          const ring = gridRefToPolygon(cell.cellId);
          if (!ring) return [];
          return [{
            type: "Feature" as const,
            geometry: { type: "Polygon" as const, coordinates: [ring] },
            properties: {
              cellId: cell.cellId,
              recordCount: cell.recordCount,
              precisionMetres: cell.precisionMetres,
            },
          }];
        })
      : [],
  }), [readyCells]);
  const canonicalCells = useMemo(() => fc.features.flatMap((feature) => {
    if (feature.geometry.type !== "Polygon" || typeof feature.properties?.cellId !== "string") {
      return [];
    }
    const ring = feature.geometry.coordinates[0];
    if (!ring) return [];
    const typedRing = ring.flatMap((position): [number, number][] => {
      const lng = position[0];
      const lat = position[1];
      return typeof lng === "number" && typeof lat === "number"
        ? [[lng, lat]]
        : [];
    });
    return [{ cellId: feature.properties.cellId, ring: typedRing }];
  }), [fc]);

  // MapLibre only re-measures on window resize, so when the surrounding layout settles
  // (fonts, data, the species panel loading) the canvas kept a stale size and painted
  // tiles into part of the card. Observe the container and resize the map with it.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => mapRef.current?.resize());
    observer.observe(el);
    return () => observer.disconnect();
  }, [mapError, state.status]);

  // Expose the real projection and the same canonical polygons used by the <Source>,
  // but only in the explicit accessibility-test mode. Refresh it after year filtering.
  useEffect(() => {
    if (!A11Y_TEST_MODE) return;
    const map = mapRef.current?.getMap();
    if (state.status !== "ready" || !mapReady || !map) {
      removeA11yTestAdapter();
      return;
    }
    // Do not return a cleanup here: React StrictMode rehearses effect cleanup during
    // development and can otherwise erase the bridge after MapLibre's load event. A
    // non-ready data state removes it explicitly; a ready rerender safely replaces it.
    installA11yTestAdapter(
      { map, canonicalCells, selectableLayers: ["cells-fill"] },
      A11Y_TEST_MODE,
    );
  }, [canonicalCells, mapReady, state.status]);

  const pan = useCallback((direction: PanDirection) => {
    mapRef.current?.getMap().panBy(PAN_OFFSETS[direction], {
      duration: prefersReducedMotion ? 0 : 250,
    });
  }, [prefersReducedMotion]);

  const onClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const f = e.features?.[0];
      onSelectCell?.(f && f.properties ? String(f.properties.cellId) : null);
      // Explore mode: the click also places the query centre. Both happen, so clicking a
      // square both selects it and asks "what else is near here" — one gesture, and the
      // selected-square readout still explains what was clicked.
      onPickCentre?.([e.lngLat.lng, e.lngLat.lat]);
    },
    [onSelectCell, onPickCentre],
  );

  // The query area, as GeoJSON. Memoised on the centre and radius so panning the map
  // does not rebuild it.
  const radiusFc = useMemo<FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: radius
      ? [{
          type: "Feature" as const,
          geometry: { type: "Polygon" as const, coordinates: [circleRing(radius.centre, radius.metres)] },
          properties: {},
        }]
      : [],
  }), [radius]);

  if (state.status === "loading") return <div className="map-card" style={box}><LoadingState label="the map" /></div>;
  if (state.status === "error") return <div className="map-card" style={box}><ErrorState message={state.error.message} onRetry={() => void query.refetch()} /></div>;
  if (state.status === "empty") return <div className="map-card" style={box}><EmptyState message={year === null ? "No mapped records for this species yet." : `No records mapped for ${year}.`} /></div>;
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
    <>
      <MapInstructions />
      <div
        className="map-card"
        ref={containerRef}
        data-a11y-test-mode={A11Y_TEST_MODE ? "true" : undefined}
        data-map-ready={A11Y_TEST_MODE ? String(mapReady) : undefined}
      >
        <Map
          ref={mapRef}
          onLoad={(e) => {
            e.target.resize();
            setMapReady(true);
          }}
          initialViewState={INITIAL_VIEW}
          mapStyle={MAP_STYLE}
          minZoom={MIN_ZOOM}
          maxZoom={MAX_ZOOM}
          interactiveLayerIds={["cells-fill"]}
          onClick={onClick}
          onError={(e) => {
            // A failed third-party raster tile must not remove the data layer and its
            // accessible table. Reserve the fatal fallback for style/WebGL failures.
            const message = e.error?.message ?? "";
            if (/webgl|context|style (?:is )?(?:invalid|failed)|failed to load style/i.test(message)) {
              setMapError(message || "unknown map error");
            }
          }}
          cooperativeGestures
          attributionControl={false}
          style={{ position: "absolute", inset: 0 }}
        >
          <NavigationControl position="bottom-right" showCompass={false} />
          <AttributionControl compact position="bottom-left" />
          {radius ? (
            <Source id="query-radius" type="geojson" data={radiusFc}>
              {/* Dashed, unfilled at the edge and barely tinted inside: it has to read as
                  a drawn search area, not as another data square. */}
              <Layer id="query-radius-fill" type="fill" paint={{ "fill-color": "#185fa5", "fill-opacity": 0.1 }} />
              <Layer id="query-radius-line" type="line" paint={{ "line-color": "#0d3d6b", "line-width": 2, "line-dasharray": [2, 1.5] }} />
            </Source>
          ) : null}
          <Source id="cells" type="geojson" data={fc}>
            <Layer {...cellsFillLayer} />
            <Layer {...cellsLineLayer} />
            <Layer id="cells-highlight-casing" type="line" filter={highlightFilter} paint={{ "line-color": "#ffffff", "line-width": 6, "line-opacity": 0.95 }} />
            <Layer id="cells-highlight" type="line" filter={highlightFilter} paint={{ "line-color": "#0b3b23", "line-width": 2.5 }} />
          </Source>
        </Map>
        <div className="map-pan-controls" role="group" aria-label="Pan map without dragging">
          {PAN_DIRECTIONS.map((direction) => (
            <button
              key={direction}
              type="button"
              className={`pan-${direction}`}
              data-map-pan={direction}
              aria-label={`Pan ${direction}`}
              onClick={() => pan(direction)}
            >
              <span aria-hidden="true">{PAN_SYMBOLS[direction]}</span>
            </button>
          ))}
        </div>
        <Legend />
      </div>
    </>
  );
}
