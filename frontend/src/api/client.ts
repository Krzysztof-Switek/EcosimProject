import type {
  DimItem,
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

async function postJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — ${path}`);
  }
  return res.json() as Promise<T>;
}

export interface ReloadResult {
  status: string;
  scenarios: string[];
  datasets: number;
  rows: number;
  files_read: number;
  errors: number;
}

export const api = {
  scenarios: () => getJson<ScenarioSummary[]>("/catalog/scenarios"),
  tree: () => getJson<ScenarioTreeNode[]>("/catalog/tree"),
  groups: () => getJson<DimItem[]>("/dictionaries/groups"),
  fleets: () => getJson<DimItem[]>("/dictionaries/fleets"),

  reload: () => postJson<ReloadResult>("/admin/reload"),

  timeseries: (params: {
    variable: string;
    freq: string;
    scenario?: string[];
    group?: string[];
    fleet?: string[];
    year_from?: number;
    year_to?: number;
  }) => {
    const q = new URLSearchParams();
    q.set("variable", params.variable);
    q.set("freq", params.freq);
    params.scenario?.forEach((s) => q.append("scenario", s));
    params.group?.forEach((g) => q.append("group", g));
    params.fleet?.forEach((f) => q.append("fleet", f));
    if (params.year_from != null) q.set("year_from", String(params.year_from));
    if (params.year_to != null) q.set("year_to", String(params.year_to));
    return getJson<TimeseriesResponse>(`/timeseries?${q.toString()}`);
  },
};
