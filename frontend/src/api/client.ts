import type {
  AnalysisSpec,
  BrowseResult,
  DataSource,
  DataSourceKind,
  ModelSummary,
  RasterEntry,
  RasterLayer,
  RegionPack,
  RegionLayersForGrid,
  AreaDefinition,
  AreaLibrary,
  AreaSummary,
  AuthStatus,
  ZonalJob,
  ZonalRequest,
  ZonalResponse,
  SavedArea,
  RunAnalysisResponse,
  ScenarioSummary,
  RunEntry,
  ScenarioTreeNode,
  SelectionEntity,
  TimeseriesResponse,
} from "./types";

const BASE = "/api";

/** Fired when the server answers 401 -- the session ended (or was never
 * started); the app then shows the sign-in page (App.tsx). */
export const SIGNED_OUT_EVENT = "ecosim:signed-out";

/** fetch() for API calls: reports a 401 (see SIGNED_OUT_EVENT). */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(input, init);
  if (res.status === 401 && !input.startsWith(`${BASE}/auth/`)) {
    window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  }
  return res;
}

/** A GET, retried once if the connection drops or the dev proxy reports it
 * couldn't reach the API (500/502/503/504) -- a dropped response otherwise
 * leaves a view silently empty (see vite.config.ts), and a GET is safe to
 * send twice. */
export async function fetchGet(url: string): Promise<Response> {
  try {
    const res = await apiFetch(url);
    if (![500, 502, 503, 504].includes(res.status)) return res;
  } catch {
    // network error (e.g. ERR_CONNECTION_RESET) -- retry below
  }
  await new Promise((r) => setTimeout(r, 300));
  return apiFetch(url);
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetchGet(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — ${path}`);
  }
  return res.json() as Promise<T>;
}

/** An error response whose `detail` is structured data (an object with at
 * least `message`), not just a string -- so a caller can react to *which*
 * situation it is (e.g. `code: "not_local"`), not only show text. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: Record<string, unknown>,
  ) {
    super(message);
  }
}

const postJson = <T,>(path: string, body?: unknown) => sendJson<T>("POST", path, body);
const putJson = <T,>(path: string, body?: unknown) => sendJson<T>("PUT", path, body);

async function sendJson<T>(method: "POST" | "PUT", path: string, body?: unknown): Promise<T> {
  const res = await apiFetch(`${BASE}${path}`, {
    method,
    ...(body !== undefined
      ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : {}),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    if (detail?.detail && typeof detail.detail === "object") {
      throw new ApiError(String(detail.detail.message ?? res.statusText), res.status, detail.detail);
    }
    throw new Error(detail?.detail ?? `${res.status} ${res.statusText} — ${path}`);
  }
  return res.json() as Promise<T>;
}

async function deleteJson<T>(path: string): Promise<T> {
  const res = await apiFetch(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `${res.status} ${res.statusText} — ${path}`);
  }
  return res.json() as Promise<T>;
}

export interface ReloadResult {
  status: string;
  models: string[];
  scenarios: string[];
  datasets: number;
  rows: number;
  files_read: number;
  errors: number;
  rasters_indexed: number;
  spatial_errors: number;
  data_kind: "spatial" | "timeseries" | "mixed" | "montecarlo" | null;
  run_count: number;
  // Files recognised as a known-but-unsupported CSV shape (Ecospace's own
  // "export map as CSV", already fully covered by the .asc raster index;
  // region/age-structure breakdowns, not yet representable in this
  // project's schema) -- skipped cleanly, not counted in `errors`.
  skipped_unsupported: number;
  // One sentence per kind of thing the scan found but did not load.
  warnings: string[];
}

// POST .../activate now only confirms the attempt was accepted -- ingestion
// runs in the background (see backend/ecosim/ingestion/activation.py) so a
// very large dataset (verified: ~400GB/800k+ files) doesn't leave the
// request looking hung. Poll activationStatus() for live progress.
export interface ActivationStartResult {
  status: "started";
  source_id: string;
}

export interface ActivationStatus {
  status: "unknown" | "running" | "ok" | "error" | "cancelled";
  phase: string | null;
  files_done: number;
  files_total: number | null;
  result?: ReloadResult & { source_id: string };
  error?: string;
}

// Detail of the 409 POST /admin/sources returns for a folder whose files
// are cloud-only placeholders (backend api/routers/sources.py::add_source).
export interface NotLocalInfo {
  code: "not_local";
  message: string;
  cloud_only_files: number;
  cloud_only_bytes: number;
  files_checked: number;
  // Rough download time -- on-demand OneDrive downloads run ~10 files/s
  // (measured), so this scales with file count, not size.
  estimated_seconds: number;
  // False on a server: nothing there can ask a sync app to download.
  can_download: boolean;
}

export function asNotLocal(e: unknown): NotLocalInfo | null {
  return e instanceof ApiError && e.detail.code === "not_local" ? (e.detail as unknown as NotLocalInfo) : null;
}

export const api = {
  models: () => getJson<ModelSummary[]>("/catalog/models"),
  scenarios: () => getJson<ScenarioSummary[]>("/catalog/scenarios"),
  tree: () => getJson<ScenarioTreeNode[]>("/catalog/tree"),
  /** Monte Carlo runs of these scenarios (empty for ordinary output). */
  runs: (scenario: string[]) => {
    const q = new URLSearchParams();
    scenario.forEach((s) => q.append("scenario", s));
    return getJson<RunEntry[]>(`/catalog/runs?${q.toString()}`);
  },
  // A Results-Extractor box's selection window (time-series step 5).
  selection: (params: { category: string; variable: string[]; freq: string; scenario: string[] }) => {
    const q = new URLSearchParams({ category: params.category, freq: params.freq });
    params.variable.forEach((v) => q.append("variable", v));
    params.scenario.forEach((s) => q.append("scenario", s));
    return getJson<SelectionEntity[]>(`/catalog/selection?${q.toString()}`);
  },

  reload: () => postJson<ReloadResult>("/admin/reload"),

  sources: (kind?: DataSourceKind) => getJson<DataSource[]>(`/admin/sources${kind ? `?kind=${kind}` : ""}`),
  // Throws ApiError with detail.code === "not_local" (see NotLocalInfo) when
  // the folder's files aren't on this computer yet and keepLocal is false.
  addSource: (name: string, path: string, kind: DataSourceKind, keepLocal = false) =>
    postJson<DataSource>("/admin/sources", { name, path, kind, keep_local: keepLocal }),
  activateSource: (id: string) =>
    postJson<ActivationStartResult>(`/admin/sources/${encodeURIComponent(id)}/activate`),
  rescanSource: (id: string) =>
    postJson<ActivationStartResult>(`/admin/sources/${encodeURIComponent(id)}/rescan`),
  activationStatus: (id: string) =>
    getJson<ActivationStatus>(`/admin/sources/${encodeURIComponent(id)}/activation-status`),
  cancelActivation: (id: string) =>
    postJson<{ status: string; source_id: string }>(`/admin/sources/${encodeURIComponent(id)}/activation-cancel`),
  // The CRS a source's maps are really in (null = as EwE declares) -- see MapCrsMismatch.
  /** Identify which EwE models a source's files come from (reads file headers only). */
  identifySource: (id: string) => postJson<DataSource>(`/admin/sources/${encodeURIComponent(id)}/identify`),
  setMapCrs: (id: string, mapCrs: string | null) =>
    putJson<DataSource>(`/admin/sources/${encodeURIComponent(id)}/map-crs`, { map_crs: mapCrs }),
  removeSource: (id: string) => deleteJson<{ status: string }>(`/admin/sources/${encodeURIComponent(id)}`),
  browse: (path?: string, opts?: { zip?: boolean }) => {
    const q = new URLSearchParams();
    if (path) q.set("path", path);
    if (opts?.zip) q.set("zip", "true");
    const qs = q.toString();
    return getJson<BrowseResult>(`/admin/browse${qs ? `?${qs}` : ""}`);
  },
  regionPacks: () => getJson<RegionPack[]>("/regions/packs"),
  importRegionPack: (path: string, name?: string) =>
    postJson<RegionPack>("/regions/packs", { path, name: name || undefined }),
  removeRegionPack: (id: string) => deleteJson<{ removed: string }>(`/regions/packs/${encodeURIComponent(id)}`),
  regionLayers: (scenario: string, domain = "output") =>
    getJson<RegionLayersForGrid>(
      `/regions/layers?${new URLSearchParams({ scenario, domain }).toString()}`,
    ),
  regionOutlines: (layerId: string) =>
    getJson<GeoJSON.FeatureCollection>(`/regions/layers/${encodeURIComponent(layerId)}/outlines`),
  areaSummary: (body: { scenario: string; domain?: string; area: AreaDefinition; outline?: boolean }) =>
    postJson<AreaSummary>("/regions/area/summary", body),
  zonal: (body: ZonalRequest) => postJson<ZonalResponse>("/spatial/zonal", body),
  zonalJob: (id: string) => getJson<ZonalJob>(`/spatial/zonal/jobs/${encodeURIComponent(id)}`),
  cancelZonalJob: (id: string) => postJson<ZonalJob>(`/spatial/zonal/jobs/${encodeURIComponent(id)}/cancel`),
  areaLibrary: () => getJson<AreaLibrary>("/areas"),
  saveAreaLibrary: (areas: SavedArea[], selected: string[]) => putJson<AreaLibrary>("/areas", { areas, selected }),

  /** Tidy rows of one variable; `picks` = the selection of its Results-Extractor box
   * (omitted for a box without a selection window). */
  timeseries: (body: {
    variable: string;
    freq: string;
    scenario: string[];
    picks?: string[][];
    /** Monte Carlo: one run; omitted = baseline run + the samples' 5–95% band. */
    run?: string;
    year_from?: number;
    year_to?: number;
    month_from?: number;
    month_to?: number;
  }) => postJson<TimeseriesResponse>("/timeseries", body),

  /** The selected series as a zip of CSV files, one per variable ("Save Results"). */
  exportTimeseries: async (body: {
    freq: string;
    yearly: boolean;
    run?: string;
    year_from?: number;
    year_to?: number;
    month_from?: number;
    month_to?: number;
    items: { variable: string; scenarios: string[]; picks?: string[][]; selection: string }[];
  }): Promise<{ blob: Blob; filename: string }> => {
    const res = await apiFetch(`${BASE}/timeseries/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new Error(typeof detail?.detail === "string" ? detail.detail : `${res.status} ${res.statusText}`);
    }
    const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
    return { blob: await res.blob(), filename: match?.[1] ?? "ecosim_timeseries.zip" };
  },

  spatialLayers: () => getJson<RasterLayer[]>("/spatial/layers"),

  /** One (scenario, variable)'s maps -- of one Monte Carlo run if `run` is given. */
  spatialRasters: (params: { scenario: string; variable: string; run?: string }) => {
    const q = new URLSearchParams({ scenario: params.scenario, variable: params.variable });
    if (params.run) q.set("run", params.run);
    return getJson<RasterEntry[]>(`/spatial/rasters?${q.toString()}`);
  },
  /** Monte Carlo runs a variable's maps exist for (empty for ordinary maps). */
  spatialRuns: (params: { scenario: string; variable: string }) => {
    const q = new URLSearchParams({ scenario: params.scenario, variable: params.variable });
    return getJson<RunEntry[]>(`/spatial/runs?${q.toString()}`);
  },

  spatialRasterUrl: (id: string) => `${BASE}/spatial/raster/${encodeURIComponent(id)}`,

  /** The selected maps as ESRI ASCII grids, zipped (see backend export/spatial_ascii.py). */
  exportSpatialAscii: async (body: {
    scenario: string;
    /** Monte Carlo maps: the run shown. */
    run?: string;
    /** Each variable with its own groups/fleets and year range. */
    items: { variable: string; entities: string[]; year_from: number; year_to: number }[];
    areas: { name: string; geojson: GeoJSON.FeatureCollection }[];
  }): Promise<{ blob: Blob; filename: string }> => {
    const res = await apiFetch(`${BASE}/spatial/export/ascii`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new Error(typeof detail?.detail === "string" ? detail.detail : `${res.status} ${res.statusText}`);
    }
    const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
    return { blob: await res.blob(), filename: match?.[1] ?? "ecosim_ascii.zip" };
  },

  /** All registered analyses, or (with `variableNames`) only ones compatible
   * with that selection -- e.g. what's currently picked in a basket. */
  analyses: (variableNames?: string[], context?: "timeseries" | "spatial") => {
    const q = new URLSearchParams();
    variableNames?.forEach((v) => q.append("variable", v));
    if (context) q.set("context", context);
    const qs = q.toString();
    return getJson<AnalysisSpec[]>(`/analyses${qs ? `?${qs}` : ""}`);
  },

  runAnalysis: (id: string, body: { manifest: Record<string, unknown>; params: Record<string, unknown> }) =>
    postJson<RunAnalysisResponse>(`/analyses/${encodeURIComponent(id)}/run`, body),

  authStatus: () => getJson<AuthStatus>("/auth/status"),
  login: (username: string, password: string) => postJson<AuthStatus>("/auth/login", { username, password }),
  logout: () => postJson<AuthStatus>("/auth/logout"),
  artifactUrl: (jobId: string, path: string) =>
    `${BASE}/analyses/jobs/${encodeURIComponent(jobId)}/artifact/${path}`,
};
