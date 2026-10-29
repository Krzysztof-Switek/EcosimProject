import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet-draw";
import "leaflet-draw/dist/leaflet.draw.css";
import parseGeoraster from "georaster";
import type { GeoRaster } from "georaster-layer-for-leaflet";
import { fetchGet } from "../../api/client";
import type { MapCrsMismatch } from "../../api/types";
import { makeValueToColor, type PaletteId } from "./colorScale";
import { MapCrsFix } from "./MapCrsFix";

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
  // Sample at each output row's centre, and take the source row whose cell
  // contains it -- mapping row edges to edges (i / (height - 1)) shifted the
  // image by up to half a cell, visibly past an area-of-interest outline.
  for (let i = 0; i < height; i++) {
    const mercY = mercMax + (mercMin - mercMax) * ((i + 0.5) / height);
    const lat = inverseMercatorY(mercY);
    const srcFrac = (ymax - lat) / (ymax - ymin || 1);
    out[i] = Math.min(height - 1, Math.max(0, Math.floor(srcFrac * height)));
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
  return [x, frac * height];
}

/** Trace every ring of every Polygon/MultiPolygon feature of every selected area into the
 * current canvas path -- one shared subpath per ring, so a later ctx.clip() (nonzero winding)
 * masks to the union of all of them, disjoint or not. */
function traceAoiPath(ctx: CanvasRenderingContext2D, aois: GeoJSON.FeatureCollection[], georaster: GeoRaster): boolean {
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
  for (const aoi of aois) {
    for (const feature of aoi.features) {
      const g = feature.geometry;
      if (g.type === "Polygon") g.coordinates.forEach(traceRing);
      else if (g.type === "MultiPolygon") g.coordinates.forEach((poly) => poly.forEach(traceRing));
    }
  }
  return any;
}

/**
 * Render one band of a (small, fixed-extent) georaster to a colored canvas,
 * clipped to the AOI if set -- rows already warped to Web Mercator, so it
 * goes straight onto a Mercator map between the raster's corners. Fully
 * synchronous -- no tile loading, so no async gap for a swap to flicker
 * through. Also used for the frames of an exported animation
 * (exportAnimation.ts), so they look exactly like the screen.
 */
export function renderRasterCanvas(
  georaster: GeoRaster,
  aois: GeoJSON.FeatureCollection[],
  palette: PaletteId,
  invert: boolean,
  domainOverride: RasterStats | null,
): RasterStats & { canvas: HTMLCanvasElement; dataMin: number; dataMax: number } {
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
  if (aois.length > 0) {
    ctx.save();
    if (traceAoiPath(ctx, aois, georaster)) ctx.clip();
    ctx.drawImage(dataCanvas, 0, 0);
    ctx.restore();
  } else {
    ctx.drawImage(dataCanvas, 0, 0);
  }

  return { canvas, min, max, dataMin, dataMax };
}

/** renderRasterCanvas as a data URL, ready for L.imageOverlay. */
function renderRaster(
  georaster: GeoRaster,
  aois: GeoJSON.FeatureCollection[],
  palette: PaletteId,
  invert: boolean,
  domainOverride: RasterStats | null,
): RasterStats & { url: string; dataMin: number; dataMax: number } {
  const { canvas, ...stats } = renderRasterCanvas(georaster, aois, palette, invert, domainOverride);
  return { url: canvas.toDataURL(), ...stats };
}

/** A small, fixed rotation of outline colors so multiple simultaneously-selected
 * areas stay visually distinguishable on the map -- independent of the data
 * color palette, which is a different concern (magnitude, not identity). */
export const AOI_OUTLINE_COLORS = ["#eb6834", "#2f6fed", "#1fa87a", "#c23fd0", "#c2a83f", "#e0475b"];

// The furthest the map can be zoomed out or panned: one copy of the world.
const WORLD_BOUNDS = L.latLngBounds([-85, -180], [85, 180]);

/**
 * Keeps several maps showing the same view: panning or zooming one moves the
 * others (side-by-side group maps are compared cell by cell).
 */
export class MapViewSync {
  private maps = new Set<L.Map>();
  private syncing = false;
  // Each map's own "whole world in view" zoom. Maps a pixel apart in width can
  // land on different whole zoom levels, which let one of them zoom out a step
  // further than the rest -- so all of them get the lowest.
  private fitZooms = new Map<L.Map, number>();

  setFitZoom(map: L.Map, zoom: number) {
    this.fitZooms.set(map, zoom);
    this.applyMinZoom();
  }

  private applyMinZoom() {
    const min = Math.min(...this.fitZooms.values());
    for (const m of this.fitZooms.keys()) m.setMinZoom(min);
  }

  add(map: L.Map): () => void {
    const onMove = () => {
      if (this.syncing) return;
      this.syncing = true;
      try {
        for (const other of this.maps) {
          if (other !== map) other.setView(map.getCenter(), map.getZoom(), { animate: false });
        }
      } finally {
        this.syncing = false;
      }
    };
    this.maps.add(map);
    map.on("move", onMove);
    return () => {
      map.off("move", onMove);
      this.maps.delete(map);
      this.fitZooms.delete(map);
      if (this.fitZooms.size > 0) this.applyMinZoom();
    };
  }
}

/**
 * Zooming out stops at the whole world in view (to see the model's area
 * against the rest of it), never further. Without a limit, zooming out with
 * the mouse wheel showed the basemap repeated across the screen and the view
 * drifted off with no way back. Depends on the map's size, so it's re-applied
 * whenever that changes.
 */
function limitZoomToWorld(map: L.Map, viewSync?: MapViewSync) {
  const worldZoom = map.getBoundsZoom(WORLD_BOUNDS);
  if (viewSync) viewSync.setFitZoom(map, worldZoom);
  else map.setMinZoom(worldZoom);
}

export function RasterMap({
  rasterUrl,
  prefetchUrl,
  onStats,
  selectedAois,
  onAoiDrawn,
  palette,
  invert,
  domainOverride,
  reloadToken = 0,
  onCrsFixed,
  viewSync,
}: {
  rasterUrl: string | null;
  /** Fetched+parsed into the cache in the background, without touching the visible layer. */
  prefetchUrl?: string | null;
  onStats: (stats: (RasterStats & { dataMin: number; dataMax: number }) | null) => void;
  /** Every area currently checked in the parent's named-area library -- the map shows the
   * outline of each and clips the raster to their union (empty array = full map). */
  selectedAois: { id: string; name: string; geojson: GeoJSON.FeatureCollection }[];
  /** A new shape was drawn on the map -- parent should create + select a named entry for it. */
  onAoiDrawn: (geojson: GeoJSON.FeatureCollection) => void;
  palette: PaletteId;
  invert: boolean;
  /** Manual color-scale domain; null means auto (scale to this raster's own min/max). */
  domainOverride: RasterStats | null;
  /** Bumped by the parent after a source's CRS is fixed: same URLs, but the server now
   * converts differently, so everything cached is stale. */
  reloadToken?: number;
  /** The CRS was fixed from this map's panel -- the parent bumps reloadToken for every map. */
  onCrsFixed: () => void;
  /** Shared with the other maps on screen so they all pan/zoom together. */
  viewSync?: MapViewSync;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlayRef = useRef<L.ImageOverlay | null>(null);
  const fittedRef = useRef<string | null>(null); // extent the view was last fitted to
  const extentRef = useRef<L.LatLngBounds | null>(null); // grid the view was last fitted to
  const reloadTokenRef = useRef(reloadToken);
  const drawnItemsRef = useRef<L.FeatureGroup | null>(null);
  const displayLayerRef = useRef<L.LayerGroup | null>(null);
  // Parsed rasters are immutable once fetched (raw .asc is immutable, and the
  // materialized COG never changes) -- cache them so revisiting a year
  // (autoplay loop, slider scrub back and forth) is instant, no refetch/reparse.
  const cacheRef = useRef<Map<string, GeoRaster>>(new Map());
  const [georaster, setGeoraster] = useState<GeoRaster | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The map's declared CRS can't be right -- offer to pick the real one (MapCrsFix).
  const [crsMismatch, setCrsMismatch] = useState<MapCrsMismatch | null>(null);

  // Create the base map, its draw toolbar, and the editable AOI layer group once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center: BALTIC_CENTER,
      zoom: BALTIC_ZOOM,
      maxBounds: WORLD_BOUNDS,
      maxBoundsViscosity: 1, // a hard edge, not a rubber band
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 12,
      noWrap: true, // one world, not copies of it side by side
    }).addTo(map);

    // Scratch group only -- used to build GeoJSON from a freshly-drawn shape
    // (.toGeoJSON()), then cleared immediately. Never added to the map: the
    // persistent, possibly-multi-shape display is displayLayer below, driven
    // by the parent's selection state, not by leaflet-draw's own bookkeeping.
    const drawnItems = new L.FeatureGroup();
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
      // No edit toolbar: reshape handles were confusing, and deleting a saved
      // area is a sidebar action (checkbox list below) now that several can
      // be shown/selected at once -- a map-side delete tool would only ever
      // have the current in-progress shape to act on.
    });
    map.addControl(drawControl);

    const displayLayer = new L.LayerGroup().addTo(map);
    displayLayerRef.current = displayLayer;

    map.on(L.Draw.Event.CREATED, (e) => {
      const layer = (e as L.DrawEvents.Created).layer;
      drawnItems.addLayer(layer);
      // A freshly-drawn shape is a *new* named area -- the parent creates it
      // and adds it to the selection; this map draws it via displayLayer once
      // that selection comes back down as a prop, so the scratch group can be
      // cleared right away.
      onAoiDrawn(drawnItems.toGeoJSON() as GeoJSON.FeatureCollection);
      drawnItems.clearLayers();
    });

    mapRef.current = map;
    const leaveSync = viewSync?.add(map);
    limitZoomToWorld(map, viewSync);
    // The container changes size when maps are added or removed beside it --
    // re-measure, and re-frame the grid for the new size.
    const resizeObserver = new ResizeObserver(() => {
      map.invalidateSize({ animate: false });
      limitZoomToWorld(map, viewSync);
      if (extentRef.current) map.fitBounds(extentRef.current, { animate: false });
    });
    resizeObserver.observe(containerRef.current);
    return () => {
      resizeObserver.disconnect();
      leaveSync?.();
      map.remove();
      mapRef.current = null;
      drawnItemsRef.current = null;
      displayLayerRef.current = null;
      overlayRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the display layer in sync with whichever areas are currently
  // selected -- each gets its own outline color (cycled) plus a name tooltip,
  // so multiple simultaneously-shown areas stay distinguishable.
  useEffect(() => {
    const displayLayer = displayLayerRef.current;
    if (!displayLayer) return;
    displayLayer.clearLayers();
    selectedAois.forEach((aoi, i) => {
      L.geoJSON(aoi.geojson, {
        style: { color: AOI_OUTLINE_COLORS[i % AOI_OUTLINE_COLORS.length], weight: 2, fillOpacity: 0 },
      })
        .bindTooltip(aoi.name, { sticky: true })
        .addTo(displayLayer);
    });
  }, [selectedAois]);

  // Fetch + parse the raster whenever the target URL changes (cached after first view).
  useEffect(() => {
    if (!rasterUrl) {
      setGeoraster(null);
      setError(null);
      setLoading(false);
      return;
    }
    if (reloadTokenRef.current !== reloadToken) {
      reloadTokenRef.current = reloadToken;
      cacheRef.current.clear(); // everything parsed so far was converted under the old CRS
    }
    const cached = cacheRef.current.get(rasterUrl);
    if (cached) {
      setGeoraster(cached);
      setError(null);
      return;
    }

    let cancelled = false;
    setError(null);
    setCrsMismatch(null);
    const showLoadingTimer = setTimeout(() => {
      if (!cancelled) setLoading(true);
    }, LOADING_INDICATOR_DELAY_MS);

    fetchGet(rasterUrl)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          if (body?.detail?.code === "map_crs_mismatch") {
            if (!cancelled) setCrsMismatch(body.detail as MapCrsMismatch);
            throw new Error(body.detail.message);
          }
          throw new Error(typeof body?.detail === "string" ? body.detail : `${res.status} ${res.statusText}`);
        }
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
  }, [rasterUrl, reloadToken]);

  // Warm the cache for the predicted next raster (autoplay/scrubbing forward)
  // while the current one is on screen, so that transition is a cache hit
  // instead of a fresh fetch+parse -- hides the ~100-500ms server-side
  // materialize-on-first-view cost behind the time the current frame is shown.
  useEffect(() => {
    if (!prefetchUrl || cacheRef.current.has(prefetchUrl)) return;
    let cancelled = false;
    fetchGet(prefetchUrl)
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

    const aoiGeojsons = selectedAois.map((a) => a.geojson);
    const { url, min, max, dataMin, dataMax } = renderRaster(georaster, aoiGeojsons, palette, invert, domainOverride);
    const bounds = L.latLngBounds([georaster.ymin, georaster.xmin], [georaster.ymax, georaster.xmax]);
    if (overlayRef.current) {
      overlayRef.current.setUrl(url);
      // Normally the same fixed grid every frame, but not after a source's
      // CRS is corrected (the reprojected grid has different bounds).
      overlayRef.current.setBounds(bounds);
    } else {
      overlayRef.current = L.imageOverlay(url, bounds).addTo(map);
    }
    // Fit once per grid extent, so stepping through years never
    // moves the user's view, but a different grid (another model, a CRS fix)
    // is framed.
    const boundsKey = [georaster.xmin, georaster.ymin, georaster.xmax, georaster.ymax].join(",");
    if (fittedRef.current !== boundsKey) {
      extentRef.current = bounds;
      map.fitBounds(bounds, { animate: false });
      fittedRef.current = boundsKey;
    }
    onStats({ min, max, dataMin, dataMax });
    // Depend on the override's primitive values, not its object identity --
    // a caller re-creating the object every render (as SpatialView did
    // before memoizing it) must not re-trigger this effect forever. selectedAois
    // is safe to depend on directly since the parent memoizes it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [georaster, selectedAois, palette, invert, domainOverride?.min, domainOverride?.max]);

  return (
    <div className="rastermap">
      <div ref={containerRef} className="rastermap__canvas" />
      {loading && <div className="rastermap__overlay muted">Loading map…</div>}
      {crsMismatch ? (
        <MapCrsFix
          info={crsMismatch}
          onApplied={() => {
            setCrsMismatch(null);
            onCrsFixed();
          }}
        />
      ) : (
        error && <div className="rastermap__overlay error">Failed to load raster: {error}</div>
      )}
    </div>
  );
}
