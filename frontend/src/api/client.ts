import type {
  AnalysisSpec,
  BrowseResult,
  DataSource,
  DataSourceKind,
  DimItem,
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

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    ...(body !== undefined
      ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : {}),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `${res.status} ${res.statusText} — ${path}`);
  }
  return res.json() as Promise<T>;
}

export interface ReloadResult {
  status: string;
  // Only present on POST /admin/sources/{id}/activate, not on the generic
  // /admin/reload (which just re-scans whatever is already active).
  source_id?: string;
  models: string[];
  scenarios: string[];
  datasets: number;
  rows: number;
  files_read: number;
  errors: number;
  rasters_indexed: number;
  spatial_errors: number;
  group_dictionary_found: boolean;
}

export const api = {
  models: () => getJson<ModelSummary[]>("/catalog/models"),
  scenarios: () => getJson<ScenarioSummary[]>("/catalog/scenarios"),
  tree: () => getJson<ScenarioTreeNode[]>("/catalog/tree"),
  groups: () => getJson<DimItem[]>("/dictionaries/groups"),
  fleets: () => getJson<DimItem[]>("/dictionaries/fleets"),

  reload: () => postJson<ReloadResult>("/admin/reload"),

  sources: (kind?: DataSourceKind) => getJson<DataSource[]>(`/admin/sources${kind ? `?kind=${kind}` : ""}`),
  addSource: (name: string, path: string, kind: DataSourceKind) =>
    postJson<DataSource>("/admin/sources", { name, path, kind }),
  activateSource: (id: string) => postJson<ReloadResult>(`/admin/sources/${encodeURIComponent(id)}/activate`),
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
