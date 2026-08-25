import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet-draw";
import "leaflet-draw/dist/leaflet.draw.css";
import parseGeoraster from "georaster";
import type { GeoRaster } from "georaster-layer-for-leaflet";
import { makeValueToColor, type PaletteId } from "./colorScale";

const BALTIC_CENTER: [number, number] = [58.5, 19.5];
const BALTIC_ZOOM = 5;
// Only show the loading indicator if a fetch is slow -- avoids a flash of
// "Loading…" on every year change when the raster is already cached.
const LOADING_INDICATOR_DELAY_MS = 200;

export interface RasterStats {
  min: number;
  max: number;
}

// The source grid (.asc / COG) is equirectangular (EPSG:4326): a degree of
// latitude always spans the same pixel distance. Leaflet's default map CRS
// (and every standard XYZ basemap, including OSM) is Web Mercator
// (EPSG:3857), which stretches latitude non-linearly -- more so further from
// the equator. L.ImageOverlay only positions an image's four corners
// correctly and stretches *linearly* in between, so an unmodified
// equirectangular image visibly drifts from the true coastline away from
// those corners (worst around the vertical middle, growing toward the
// poleward edge) -- across our ~54-66N span that's tens of pixels, exactly
// the "coastline doesn't line up" the user spotted. The fix: resample rows
// so pixel position is linear in Mercator space instead of in degrees, i.e.
// pre-warp the image to match how Leaflet will stretch it.
function mercatorY(latDeg: number): number {
  const latRad = (latDeg * Math.PI) / 180;
  return Math.log(Math.tan(Math.PI / 4 + latRad / 2));
}
function inverseMercatorY(y: number): number {
  return ((2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180) / Math.PI;
}

/** For each output row (linear in Mercator Y between ymax and ymin), the
 * equirectangular source row to sample -- nearest-neighbour is plenty at
 * this grid resolution (~0.033 degrees/cell). */
function buildRowReprojection(height: number, ymin: number, ymax: number): Int32Array {
  const mercMax = mercatorY(ymax);
  const mercMin = mercatorY(ymin);
  const out = new Int32Array(height);
  for (let i = 0; i < height; i++) {
    const mercY = mercMax + (mercMin - mercMax) * (height === 1 ? 0 : i / (height - 1));
    const lat = inverseMercatorY(mercY);
    const srcFrac = (ymax - lat) / (ymax - ymin || 1);
    out[i] = Math.min(height - 1, Math.max(0, Math.round(srcFrac * (height - 1))));
  }
  return out;
}

/** lon/lat -> canvas pixel, matching the same Mercator row-warp as the raster image
 * (longitude/columns are linear in both projections, so only latitude needs it). */
function projectToPixel(
  lon: number,
  lat: number,
  xmin: number,
  ymin: number,
  ymax: number,
  pixelWidth: number,
  height: number,
): [number, number] {
  const x = (lon - xmin) / pixelWidth;
  const mercMax = mercatorY(ymax);
  const mercMin = mercatorY(ymin);
  const frac = (mercatorY(lat) - mercMax) / (mercMin - mercMax || 1);
  return [x, frac * (height - 1)];
}

/** Trace every ring of every Polygon/MultiPolygon feature into the current canvas path. */
function traceAoiPath(ctx: CanvasRenderingContext2D, aoi: GeoJSON.FeatureCollection, georaster: GeoRaster): boolean {
  const { xmin, ymin, ymax, pixelWidth, height } = georaster;
  let any = false;
  const traceRing = (ring: number[][]) => {
    any = true;
    ring.forEach(([lon, lat], i) => {
      const [x, y] = projectToPixel(lon, lat, xmin, ymin, ymax, pixelWidth, height);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
  };
  ctx.beginPath();
  for (const feature of aoi.features) {
    const g = feature.geometry;
    if (g.type === "Polygon") g.coordinates.forEach(traceRing);
    else if (g.type === "MultiPolygon") g.coordinates.forEach((poly) => poly.forEach(traceRing));
  }
  return any;
}

/**
 * Render one band of a (small, fixed-extent) georaster to a colored canvas,
 * clipped to the AOI if set, as a data URL ready for L.imageOverlay. Fully
 * synchronous -- no tile loading, so no async gap for a swap to flicker through.
 */
function renderRaster(
  georaster: GeoRaster,
  aoi: GeoJSON.FeatureCollection | null,
  palette: PaletteId,
  invert: boolean,
  domainOverride: RasterStats | null,
): RasterStats & { url: string; dataMin: number; dataMax: number } {
  const band = georaster.values?.[0];
  if (!band) throw new Error("Raster has no pixel data");
  const { width, height, noDataValue, ymin, ymax } = georaster;

  let dataMin = Infinity;
  let dataMax = -Infinity;
  for (const row of band) {
    for (const v of row) {
      if (v == null || Number.isNaN(v) || (noDataValue != null && v === noDataValue)) continue;
      if (v < dataMin) dataMin = v;
      if (v > dataMax) dataMax = v;
    }
  }
  if (!Number.isFinite(dataMin) || !Number.isFinite(dataMax)) {
    dataMin = 0;
    dataMax = 0;
  }
  const { min, max } = domainOverride ?? { min: dataMin, max: dataMax };
  const toColor = makeValueToColor(min, max, noDataValue, palette, invert);

  const rowSrc = buildRowReprojection(height, ymin, ymax);
  const dataCanvas = document.createElement("canvas");
  dataCanvas.width = width;
  dataCanvas.height = height;
  const dctx = dataCanvas.getContext("2d")!;
  const imgData = dctx.createImageData(width, height);
  for (let r = 0; r < height; r++) {
    const row = band[rowSrc[r]]; // Mercator-linear output row <- equirectangular source row
    for (let c = 0; c < width; c++) {
      const rgb = toColor(row[c]);
      if (!rgb) continue; // leave transparent (alpha 0)
      const i = (r * width + c) * 4;
      imgData.data[i] = rgb[0];
      imgData.data[i + 1] = rgb[1];
      imgData.data[i + 2] = rgb[2];
      imgData.data[i + 3] = 255;
    }
  }
  dctx.putImageData(imgData, 0, 0);

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;
  if (aoi) {
    ctx.save();
    if (traceAoiPath(ctx, aoi, georaster)) ctx.clip();
    ctx.drawImage(dataCanvas, 0, 0);
    ctx.restore();
  } else {
    ctx.drawImage(dataCanvas, 0, 0);
  }

  return { url: canvas.toDataURL(), min, max, dataMin, dataMax };
}

export function RasterMap({
  rasterUrl,
  prefetchUrl,
  onStats,
  activeAoi,
  onAoiDrawn,
  onAoiCleared,
  palette,
  invert,
  domainOverride,
}: {
  rasterUrl: string | null;
  /** Fetched+parsed into the cache in the background, without touching the visible layer. */
  prefetchUrl?: string | null;
  onStats: (stats: (RasterStats & { dataMin: number; dataMax: number }) | null) => void;
  /** The currently-active saved area (from the parent's named-area library), or null for none. */
  activeAoi: GeoJSON.FeatureCollection | null;
  /** A new shape was drawn on the map -- parent should create + activate a named entry for it. */
  onAoiDrawn: (geojson: GeoJSON.FeatureCollection) => void;
  /** The active shape was deleted via the map's own toolbar -- parent should just deactivate it. */
  onAoiCleared: () => void;
  palette: PaletteId;
  invert: boolean;
  /** Manual color-scale domain; null means auto (scale to this raster's own min/max). */
  domainOverride: RasterStats | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlayRef = useRef<L.ImageOverlay | null>(null);
  const fittedRef = useRef(false);
  const drawnItemsRef = useRef<L.FeatureGroup | null>(null);
  const suppressNextAoiSyncRef = useRef(false);
  // Parsed rasters are immutable once fetched (raw .asc is immutable, and the
  // materialized COG never changes) -- cache them so revisiting a year
  // (autoplay loop, slider scrub back and forth) is instant, no refetch/reparse.
  const cacheRef = useRef<Map<string, GeoRaster>>(new Map());
  const [georaster, setGeoraster] = useState<GeoRaster | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create the base map, its draw toolbar, and the editable AOI layer group once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { center: BALTIC_CENTER, zoom: BALTIC_ZOOM });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 12,
    }).addTo(map);

    const drawnItems = new L.FeatureGroup().addTo(map);
    drawnItemsRef.current = drawnItems;
    const drawControl = new L.Control.Draw({
      position: "topright",
      draw: {
        // Rectangle's click-drag interaction reads as confusing next to
        // polygon's click-to-place-vertices flow; a rectangle is just a
        // 4-click polygon, so only offer the one tool.
        polygon: { showArea: true, shapeOptions: { color: "#eb6834" } },
        rectangle: false,
        circle: false,
        circlemarker: false,
        marker: false,
        polyline: false,
      },
      // Delete-only: reshape handles (the "squares at the corners") add a
      // second, confusing way to change the area -- redraw or upload instead.
      edit: { featureGroup: drawnItems, edit: false },
    });
    map.addControl(drawControl);

    map.on(L.Draw.Event.CREATED, (e) => {
      drawnItems.clearLayers(); // the map only ever shows the active area
      const layer = (e as L.DrawEvents.Created).layer;
      drawnItems.addLayer(layer);
      suppressNextAoiSyncRef.current = true;
      // A freshly-drawn shape is a *new* named area, not an edit of the
      // active one -- the parent creates + activates a library entry for it.
      onAoiDrawn(drawnItems.toGeoJSON() as GeoJSON.FeatureCollection);
    });
    map.on(L.Draw.Event.DELETED, () => {
      // Map-toolbar delete only deactivates (unclips the view); the named
      // library entry itself is managed from the sidebar list.
      suppressNextAoiSyncRef.current = true;
      onAoiCleared();
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      drawnItemsRef.current = null;
      overlayRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the editable layer group in sync with the active area whenever it
  // changes for a reason other than this map's own draw/delete handlers
  // (switching which saved area is active, an upload, load from storage) --
  // skip the round-trip when the change was just emitted by those handlers.
  useEffect(() => {
    const drawnItems = drawnItemsRef.current;
    if (!drawnItems) return;
    if (suppressNextAoiSyncRef.current) {
      suppressNextAoiSyncRef.current = false;
      return;
    }
    drawnItems.clearLayers();
    if (activeAoi) L.geoJSON(activeAoi).eachLayer((l) => drawnItems.addLayer(l));
  }, [activeAoi]);

  // Fetch + parse the raster whenever the target URL changes (cached after first view).
  useEffect(() => {
    if (!rasterUrl) {
      setGeoraster(null);
      setError(null);
      setLoading(false);
      return;
    }
    const cached = cacheRef.current.get(rasterUrl);
    if (cached) {
      setGeoraster(cached);
      setError(null);
      return;
    }

    let cancelled = false;
    setError(null);
    const showLoadingTimer = setTimeout(() => {
      if (!cancelled) setLoading(true);
    }, LOADING_INDICATOR_DELAY_MS);

    fetch(rasterUrl)
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.arrayBuffer();
      })
      .then(parseGeoraster)
      .then((g) => {
        if (cancelled) return;
        cacheRef.current.set(rasterUrl, g);
        setGeoraster(g);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message);
        setGeoraster(null);
      })
      .finally(() => {
        clearTimeout(showLoadingTimer);
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      clearTimeout(showLoadingTimer);
    };
  }, [rasterUrl]);

  // Warm the cache for the predicted next raster (autoplay/scrubbing forward)
  // while the current one is on screen, so that transition is a cache hit
  // instead of a fresh fetch+parse -- hides the ~100-500ms server-side
  // materialize-on-first-view cost behind the time the current frame is shown.
  useEffect(() => {
    if (!prefetchUrl || cacheRef.current.has(prefetchUrl)) return;
    let cancelled = false;
    fetch(prefetchUrl)
      .then((res) => (res.ok ? res.arrayBuffer() : Promise.reject(new Error(String(res.status)))))
      .then(parseGeoraster)
      .then((g) => {
        if (!cancelled) cacheRef.current.set(prefetchUrl, g);
      })
      .catch(() => {}); // best-effort: a real request will just fetch it again on demand
    return () => {
      cancelled = true;
    };
  }, [prefetchUrl]);

  // Render + swap the visible overlay whenever the parsed raster or the AOI
  // mask changes. Rendering is synchronous (plain canvas work, no tile
  // loading), so setUrl() on the existing overlay never has a blank gap to
  // flicker through -- the browser keeps showing the old image until the new
  // one (already-decoded data: URI) is ready.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!georaster) {
      if (overlayRef.current) {
        map.removeLayer(overlayRef.current);
        overlayRef.current = null;
      }
      onStats(null);
      return;
    }

    const { url, min, max, dataMin, dataMax } = renderRaster(georaster, activeAoi, palette, invert, domainOverride);
    const bounds: L.LatLngBoundsExpression = [
      [georaster.ymin, georaster.xmin],
      [georaster.ymax, georaster.xmax],
    ];
    if (overlayRef.current) {
      overlayRef.current.setUrl(url);
    } else {
      overlayRef.current = L.imageOverlay(url, bounds).addTo(map);
    }
    if (!fittedRef.current) {
      map.fitBounds(bounds);
      fittedRef.current = true;
    }
    onStats({ min, max, dataMin, dataMax });
    // Depend on the override's primitive values, not its object identity --
    // a caller re-creating the object every render (as SpatialView did
    // before memoizing it) must not re-trigger this effect forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [georaster, activeAoi, palette, invert, domainOverride?.min, domainOverride?.max]);

  return (
    <div className="rastermap">
      <div ref={containerRef} className="rastermap__canvas" />
      {loading && <div className="rastermap__overlay muted">Loading map…</div>}
      {error && <div className="rastermap__overlay error">Failed to load raster: {error}</div>}
    </div>
  );
}
