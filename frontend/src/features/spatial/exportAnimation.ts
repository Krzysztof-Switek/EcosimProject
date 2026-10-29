import parseGeoraster from "georaster";
import type { GeoRaster } from "georaster-layer-for-leaflet";
import { GIFEncoder, applyPalette, quantize } from "gifenc";
import { api, fetchGet } from "../../api/client";
import type { RasterEntry } from "../../api/types";
import { makeValueToColor, type PaletteId } from "./colorScale";
import { AOI_OUTLINE_COLORS, renderRasterCanvas, type RasterStats } from "./RasterMap";
import { formatValue } from "./RasterLegend";

/**
 * Animated GIF export: the map animation as it plays on screen -- same
 * colours (renderRasterCanvas, the map's own renderer), same OpenStreetMap
 * background, the area of interest clipped and outlined, plus the year, the
 * title and the legend drawn into each frame so the file stands on its own.
 * Built entirely in the browser; the rasters come from the same endpoint the
 * map uses (converted on the server on first request, then cached).
 */

const FRAME_DELAY_MS = 700; // the on-screen autoplay speed (SpatialView)
const MAX_MAP_W = 960;
const MAX_MAP_H = 640;
const HEADER_H = 34;
const FOOTER_H = 50;
const TILE = 256;
const TILE_URL = (z: number, x: number, y: number) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;
const MAX_LAT = 85;

export interface AnimationJob {
  area: { name: string; geojson: GeoJSON.FeatureCollection | null };
  /** Position among the selected areas -- picks the same outline colour as the map. */
  areaIndex: number;
  variableLabel: string;
  entity: string | null;
  /** One per year, in the selected range, sorted by year. */
  rasters: RasterEntry[];
  /** The variable's own colour scale (SpatialView's VariableSettings). */
  style: AnimationStyle;
  fileName: string;
}

export interface AnimationStyle {
  title: string; // e.g. the scenario, shown under the group name
  palette: PaletteId;
  invert: boolean;
  domainOverride: RasterStats | null;
}

export type ProgressFn = (done: number, total: number) => void;

export class ExportCancelled extends Error {}

/** Global Web Mercator pixel coordinates at zoom z. */
function mercX(lon: number, z: number): number {
  return ((lon + 180) / 360) * TILE * 2 ** z;
}
function mercY(lat: number, z: number): number {
  const phi = (Math.max(-MAX_LAT, Math.min(MAX_LAT, lat)) * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(phi) + 1 / Math.cos(phi)) / Math.PI) / 2) * TILE * 2 ** z;
}

interface Extent {
  west: number;
  south: number;
  east: number;
  north: number;
}

function geojsonExtent(fc: GeoJSON.FeatureCollection): Extent | null {
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
  const visit = (ring: number[][]) => {
    for (const [lon, lat] of ring) {
      west = Math.min(west, lon); east = Math.max(east, lon);
      south = Math.min(south, lat); north = Math.max(north, lat);
    }
  };
  for (const f of fc.features) {
    const g = f.geometry;
    if (g.type === "Polygon") g.coordinates.forEach(visit);
    else if (g.type === "MultiPolygon") g.coordinates.forEach((p) => p.forEach(visit));
  }
  return Number.isFinite(west) ? { west, south, east, north } : null;
}

function pad(e: Extent, frac: number): Extent {
  const dx = (e.east - e.west) * frac;
  const dy = (e.north - e.south) * frac;
  return {
    west: Math.max(-180, e.west - dx), east: Math.min(180, e.east + dx),
    south: Math.max(-MAX_LAT, e.south - dy), north: Math.min(MAX_LAT, e.north + dy),
  };
}

/** The frame's projection: a zoom level with a scale so the extent fills at most MAX_MAP_W x MAX_MAP_H. */
interface View {
  z: number;
  scale: number;
  x0: number;
  y0: number;
  width: number; // map area, px
  height: number;
}

function viewFor(e: Extent): View {
  let z = 12;
  while (z > 0 && (mercX(e.east, z) - mercX(e.west, z) > MAX_MAP_W || mercY(e.south, z) - mercY(e.north, z) > MAX_MAP_H)) z--;
  const w = mercX(e.east, z) - mercX(e.west, z);
  const h = mercY(e.south, z) - mercY(e.north, z);
  const scale = Math.min(MAX_MAP_W / w, MAX_MAP_H / h, 2);
  return {
    z, scale, x0: mercX(e.west, z), y0: mercY(e.north, z),
    width: Math.round(w * scale), height: Math.round(h * scale),
  };
}

const toPx = (v: View, lon: number, lat: number): [number, number] => [
  (mercX(lon, v.z) - v.x0) * v.scale,
  (mercY(lat, v.z) - v.y0) * v.scale + HEADER_H,
];

function loadImage(url: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous"; // needed to read the composed frame back (getImageData)
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

/** The OSM background for one view, fetched once and reused for every frame. Null if any tile failed. */
async function basemap(v: View): Promise<HTMLCanvasElement | null> {
  const canvas = document.createElement("canvas");
  canvas.width = v.width;
  canvas.height = v.height;
  const ctx = canvas.getContext("2d")!;
  const n = 2 ** v.z;
  const tx0 = Math.floor(v.x0 / TILE);
  const tx1 = Math.floor((v.x0 + v.width / v.scale) / TILE);
  const ty0 = Math.max(0, Math.floor(v.y0 / TILE));
  const ty1 = Math.min(n - 1, Math.floor((v.y0 + v.height / v.scale) / TILE));
  const jobs: Promise<boolean>[] = [];
  for (let tx = tx0; tx <= tx1; tx++) {
    for (let ty = ty0; ty <= ty1; ty++) {
      const wrapped = ((tx % n) + n) % n;
      jobs.push(
        loadImage(TILE_URL(v.z, wrapped, ty)).then((img) => {
          if (!img) return false;
          const size = TILE * v.scale;
          ctx.drawImage(img, (tx * TILE - v.x0) * v.scale, (ty * TILE - v.y0) * v.scale, size + 0.5, size + 0.5);
          return true;
        }),
      );
    }
  }
  const ok = await Promise.all(jobs);
  return ok.every(Boolean) ? canvas : null;
}

function drawOutline(ctx: CanvasRenderingContext2D, v: View, fc: GeoJSON.FeatureCollection, color: string) {
  const ring = (r: number[][]) => {
    r.forEach(([lon, lat], i) => {
      const [x, y] = toPx(v, lon, lat);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
  };
  ctx.beginPath();
  for (const f of fc.features) {
    const g = f.geometry;
    if (g.type === "Polygon") g.coordinates.forEach(ring);
    else if (g.type === "MultiPolygon") g.coordinates.forEach((p) => p.forEach(ring));
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();
}

function drawFrame(
  ctx: CanvasRenderingContext2D,
  v: View,
  job: AnimationJob,
  background: HTMLCanvasElement | null,
  georaster: GeoRaster,
  year: number,
) {
  const W = v.width;
  const { style } = job;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, W, HEADER_H + v.height + FOOTER_H);

  // Map: background, data (exactly as on screen), area outline, attribution.
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, HEADER_H, W, v.height);
  ctx.clip();
  if (background) ctx.drawImage(background, 0, HEADER_H);
  else {
    ctx.fillStyle = "#e8ecef";
    ctx.fillRect(0, HEADER_H, W, v.height);
  }
  const rendered = renderRasterCanvas(
    georaster,
    job.area.geojson ? [job.area.geojson] : [],
    style.palette,
    style.invert,
    style.domainOverride,
  );
  const [rx0, ry0] = toPx(v, georaster.xmin, georaster.ymax);
  const [rx1, ry1] = toPx(v, georaster.xmax, georaster.ymin);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(rendered.canvas, rx0, ry0, rx1 - rx0, ry1 - ry0);
  if (job.area.geojson) {
    drawOutline(ctx, v, job.area.geojson, AOI_OUTLINE_COLORS[job.areaIndex % AOI_OUTLINE_COLORS.length]);
  }
  ctx.font = "11px sans-serif";
  const attribution = background ? "© OpenStreetMap contributors" : "";
  if (attribution) {
    const tw = ctx.measureText(attribution).width;
    ctx.fillStyle = "rgba(255,255,255,0.8)";
    ctx.fillRect(W - tw - 8, HEADER_H + v.height - 16, tw + 8, 16);
    ctx.fillStyle = "#333";
    ctx.fillText(attribution, W - tw - 4, HEADER_H + v.height - 4);
  }
  ctx.restore();

  // Header: what it is, and the year.
  ctx.fillStyle = "#1d2433";
  ctx.font = "bold 15px sans-serif";
  const name = job.entity ?? job.variableLabel;
  ctx.fillText(name, 10, 22);
  const nameW = ctx.measureText(name).width;
  ctx.font = "13px sans-serif";
  ctx.fillStyle = "#5b6475";
  const areaLabel = job.area.geojson ? ` · ${job.area.name}` : "";
  ctx.fillText(`${job.entity ? `${job.variableLabel} · ` : ""}${style.title}${areaLabel}`, 18 + nameW, 22);
  ctx.font = "bold 20px sans-serif";
  ctx.fillStyle = "#1d2433";
  const yearText = String(year);
  ctx.fillText(yearText, W - ctx.measureText(yearText).width - 10, 25);

  // Footer: the legend -- <variable>  <min> [colour bar] <max> -- and, below
  // it, how the scale was set. With the auto scale each frame is scaled to
  // its own year's range, so both ends change from frame to frame; without
  // saying so, the changing number in the corner read as unexplained.
  const fy = HEADER_H + v.height + 8;
  ctx.font = "bold 12px sans-serif";
  ctx.fillStyle = "#1d2433";
  ctx.fillText(job.variableLabel, 10, fy + 12);
  ctx.font = "12px sans-serif";
  const minText = formatValue(rendered.min);
  const maxText = formatValue(rendered.max);
  const minX = 20 + ctx.measureText(job.variableLabel).width;
  const barX = minX + ctx.measureText(minText).width + 8;
  const maxW = ctx.measureText(maxText).width;
  const barW = Math.max(60, W - barX - maxW - 18);
  ctx.fillStyle = "#1d2433";
  ctx.fillText(minText, minX, fy + 12);
  const toColor = makeValueToColor(0, 1, null, style.palette, style.invert);
  for (let i = 0; i < barW; i++) {
    const [r, g, b] = toColor(i / (barW - 1)) ?? [255, 255, 255];
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    ctx.fillRect(barX + i, fy + 2, 1, 12);
  }
  ctx.fillStyle = "#1d2433";
  ctx.fillText(maxText, barX + barW + 8, fy + 12);
  ctx.font = "11px sans-serif";
  ctx.fillStyle = "#5b6475";
  const scaleNote = style.domainOverride
    ? `Colour scale: fixed, ${formatValue(style.domainOverride.min)} – ${formatValue(style.domainOverride.max)} in every frame`
    : `Colour scale: auto — each year scaled to its own min – max`;
  ctx.fillText(
    background ? scaleNote : `${scaleNote} · background map unavailable`,
    10, fy + 32,
  );
}

/**
 * Render each job to an animated GIF (one frame per raster/year). Returns the
 * files by name, plus notes for the README (e.g. a background that couldn't
 * be loaded).
 */
export async function buildAnimations(
  jobs: AnimationJob[],
  onProgress: ProgressFn,
  isCancelled: () => boolean,
): Promise<{ files: Map<string, Uint8Array>; notes: string[] }> {
  const total = jobs.reduce((n, j) => n + j.rasters.length, 0);
  let done = 0;
  onProgress(done, total);
  const georasters = new Map<string, Promise<GeoRaster>>();
  const load = (r: RasterEntry) => {
    let p = georasters.get(r.id);
    if (!p) {
      p = fetchGet(api.spatialRasterUrl(r.id)).then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          const detail = body?.detail;
          throw new Error(typeof detail === "string" ? detail : detail?.message ?? `${res.status} ${res.statusText}`);
        }
        return parseGeoraster(await res.arrayBuffer());
      });
      georasters.set(r.id, p);
    }
    return p;
  };
  const backgrounds = new Map<string, Promise<HTMLCanvasElement | null>>();
  const files = new Map<string, Uint8Array>();
  const notes: string[] = [];

  for (const job of jobs) {
    if (job.rasters.length === 0) continue;
    const first = await load(job.rasters[0]);
    const gridExtent = { west: first.xmin, south: first.ymin, east: first.xmax, north: first.ymax };
    const areaExtent = job.area.geojson ? geojsonExtent(job.area.geojson) : null;
    const v = viewFor(pad(areaExtent ?? gridExtent, areaExtent ? 0.08 : 0.04));
    const key = [v.z, v.x0, v.y0, v.width, v.height].join(",");
    if (!backgrounds.has(key)) backgrounds.set(key, basemap(v));
    const background = await backgrounds.get(key)!;
    if (!background) notes.push(`${job.fileName}: OpenStreetMap background could not be loaded, frames have a plain background.`);

    const canvas = document.createElement("canvas");
    canvas.width = v.width;
    canvas.height = HEADER_H + v.height + FOOTER_H;
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    const gif = GIFEncoder();
    // Fetch a few years ahead while the current frame is drawn and encoded.
    const ahead = 4;
    job.rasters.slice(0, ahead).forEach((r) => void load(r).catch(() => {}));
    for (let i = 0; i < job.rasters.length; i++) {
      if (isCancelled()) throw new ExportCancelled();
      if (job.rasters[i + ahead]) void load(job.rasters[i + ahead]).catch(() => {});
      const raster = job.rasters[i];
      drawFrame(ctx, v, job, background, await load(raster), raster.year);
      const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const palette = quantize(data, 256);
      gif.writeFrame(applyPalette(data, palette), canvas.width, canvas.height, { palette, delay: FRAME_DELAY_MS });
      onProgress(++done, total);
      await new Promise((r) => setTimeout(r, 0)); // keep the page responsive
    }
    gif.finish();
    files.set(job.fileName, gif.bytes());
  }
  return { files, notes };
}
