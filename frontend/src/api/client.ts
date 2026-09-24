import type {
  AnalysisSpec,
  BrowseResult,
  DataSource,
  DataSourceKind,
  ModelSummary,
  RasterEntry,
  RasterLayer,
  RunAnalysisResponse,
  ScenarioSummary,
  ScenarioTreeNode,
  TimeseriesResponse,
} from "./types";

const BASE = "/api";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
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

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
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
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
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
  removeSource: (id: string) => deleteJson<{ status: string }>(`/admin/sources/${encodeURIComponent(id)}`),
  browse: (path?: string) => {
    const q = path ? `?path=${encodeURIComponent(path)}` : "";
    return getJson<BrowseResult>(`/admin/browse${q}`);
  },

  timeseries: (params: {
    variable: string;
    freq: string;
    model?: string[];
    scenario?: string[];
    group?: string[];
    fleet?: string[];
    year_from?: number;
    year_to?: number;
    month_from?: number;
    month_to?: number;
  }) => {
    const q = new URLSearchParams();
    q.set("variable", params.variable);
    q.set("freq", params.freq);
    params.model?.forEach((m) => q.append("model", m));
    params.scenario?.forEach((s) => q.append("scenario", s));
    params.group?.forEach((g) => q.append("group", g));
    params.fleet?.forEach((f) => q.append("fleet", f));
    if (params.year_from != null) q.set("year_from", String(params.year_from));
    if (params.year_to != null) q.set("year_to", String(params.year_to));
    if (params.month_from != null) q.set("month_from", String(params.month_from));
    if (params.month_to != null) q.set("month_to", String(params.month_to));
    return getJson<TimeseriesResponse>(`/timeseries?${q.toString()}`);
  },

  spatialLayers: () => getJson<RasterLayer[]>("/spatial/layers"),

  spatialRasters: (params: { scenario: string; variable: string }) => {
    const q = new URLSearchParams({ scenario: params.scenario, variable: params.variable });
    return getJson<RasterEntry[]>(`/spatial/rasters?${q.toString()}`);
  },

  spatialRasterUrl: (id: string) => `${BASE}/spatial/raster/${encodeURIComponent(id)}`,

  /** All registered analyses, or (with `variableNames`) only ones compatible
   * with that selection -- e.g. what's currently picked in a basket. */
  analyses: (variableNames?: string[]) => {
    const q = new URLSearchParams();
    variableNames?.forEach((v) => q.append("variable", v));
    const qs = q.toString();
    return getJson<AnalysisSpec[]>(`/analyses${qs ? `?${qs}` : ""}`);
  },

  runAnalysis: (id: string, body: { manifest: Record<string, unknown>; params: Record<string, unknown> }) =>
    postJson<RunAnalysisResponse>(`/analyses/${encodeURIComponent(id)}/run`, body),

  artifactUrl: (jobId: string, path: string) =>
    `${BASE}/analyses/jobs/${encodeURIComponent(jobId)}/artifact/${path}`,

  /** Download exactly what a manifest selects as a CSV file -- no analysis, no R. */
  exportData: async (manifest: Record<string, unknown>): Promise<Response> => {
    const res = await fetch(`${BASE}/analyses/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manifest }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new Error(detail?.detail ?? `${res.status} ${res.statusText} — export`);
    }
    return res;
  },
};
