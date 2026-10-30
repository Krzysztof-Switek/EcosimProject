// Shapes returned by the FastAPI backend (see backend/ecosim/api).

export interface ScenarioSummary {
  scenario: string; // slug id
  label: string | null; // authoritative EcosimScenario name (output)
  domain: string;
  model: string | null; // parent Ecopath model id (null for input drivers)
  model_name: string | null;
  n_datasets: number;
  year_min: number;
  year_max: number;
}

export interface ScenarioRef {
  scenario: string; // slug id
  label: string; // EcosimScenario name
}

export interface ModelSummary {
  model: string; // Ecopath model id (slug of ModelName)
  model_name: string; // authoritative ModelName label
  scenarios: ScenarioRef[]; // Ecosim scenarios run under this model
  year_min: number;
  year_max: number;
  n_datasets: number;
}

export interface VariableEntry {
  variable: string;
  freq: "annual" | "monthly";
  label: string | null;
  category: string | null;
  year_min: number;
  year_max: number;
  n_groups: number;
  n_fleets: number;
  n_partners: number;
}

export interface DomainNode {
  domain: string;
  variables: VariableEntry[];
}

export interface ScenarioTreeNode {
  scenario: string;
  model: string | null; // parent Ecopath model id (null for input drivers)
  model_name: string | null;
  domains: DomainNode[];
}

export interface DimItem {
  id: number;
  name: string;
  slug: string;
}

export interface TimeseriesRow {
  model: string | null;
  model_name: string | null;
  scenario: string;
  variable: string;
  freq: string;
  date: string;
  year: number;
  month: number;
  group_id: number | null;
  group_name: string | null;
  fleet_id: number | null;
  fleet_name: string | null;
  partner_id: number | null;
  partner_name: string | null;
  value: number | null;
  /** Biomass rows: the group's Ecopath biomass B, the baseline Ecosim starts from (null if unknown). */
  baseline?: number | null;
}

/** A functional group or fleet present in the data (GET /catalog/groups, /catalog/fleets).
 * EwE numbers both per model; most output files carry only that number, so `name` is
 * usually null (no id->name dictionary exists -- see docs/ewe-data-formats.md §5). */
export type DimensionKind = "group" | "fleet";

export interface DimensionOption {
  id: number;
  name: string | null;
  variables: string[]; // which of the requested variables contain it
}

export interface TimeseriesResponse {
  count: number;
  variable: string;
  freq: string;
  rows: TimeseriesRow[];
}

export interface RasterLayer {
  scenario: string;
  model: string | null;
  model_name: string | null;
  domain: string; // "output" | "input"
  variable: string;
  n_groups: number;
  n_fleets: number;
  year_min: number;
  year_max: number;
  n_rasters: number;
}

export interface RasterEntry {
  id: string; // "scenario|domain|variable|entity_slug|year" -- opaque, pass to the raster endpoint
  model: string | null;
  model_name: string | null;
  scenario: string;
  domain: string;
  variable: string;
  group_id: number | null;
  group_name: string | null;
  fleet_id: number | null;
  fleet_name: string | null;
  year: number;
}

export interface AnalysisParam {
  key: string;
  type: "number" | "bool" | string;
  default: unknown;
  label: string | null;
}

export interface AnalysisSpec {
  id: string;
  name: string;
  description: string | null;
  requires: {
    domain?: string;
    variables?: string[];
    dims?: string[];
  };
  params: AnalysisParam[];
  entry: string;
}

export interface AnalysisArtifact {
  type: "figure" | "table" | "map" | "scalar" | "vega_spec" | string;
  title: string | null;
  path?: string;
  value?: number;
  unit?: string | null;
}

export interface AnalysisResult {
  status: string;
  title?: string;
  artifacts: AnalysisArtifact[];
}

export interface RunAnalysisResponse {
  job_id: string;
  result: AnalysisResult;
}

export type DataSourceKind = "output" | "input";

// What the most recent successful scan actually found -- drives which
// Explore tiles (Spatial/Time series/Monte Carlo) are unlocked on the
// Landing page. null until scanned, or when nothing was ingestible.
export type DataKind = "spatial" | "timeseries" | "mixed" | "montecarlo" | null;

export interface DataSource {
  id: string;
  name: string;
  path: string;
  kind: DataSourceKind;
  added_at: string;
  last_scanned_at: string | null;
  status: "unscanned" | "ok" | "error" | string;
  error: string | null;
  active: boolean;
  data_kind: DataKind;
  run_count: number;
  // Wall-clock seconds the most recent successful (re)scan took -- null
  // until scanned, or for a source migrated from the pre-per-source-cache
  // layout whose original scan duration was never recorded. Shown next to
  // the Rescan button as a rough time estimate.
  scan_duration_seconds: number | null;
  // Total size on disk of this source's own cache slot -- NOT the shared
  // live store (catalog.duckdb, materialized COGs), which isn't
  // attributable to one specific source. 0 for a never-scanned source.
  cache_size_bytes: number;
  // What the last successful scan found but did NOT load (unrecognised map
  // files, unsupported CSV shapes, unreadable files) -- one sentence each.
  scan_warnings: string[];
  // CRS the user set for this source's maps (e.g. "EPSG:3035"); null = as EwE declares.
  map_crs: string | null;
  // Which EwE models the files come from; null = not identified yet. See ModelInventory.
  models: ModelInventory | null;
}

/** What a source's files were identified as (backend ingestion/model_origin.py).
 * Output: the EwE model layer each file came from (its "<HEADER .../>" blocks).
 * Input: the kinds of model input found. A key is absent when nothing of that
 * kind was found; not_checked counts files only in the cloud (not read). */
export interface ModelInventory {
  // groups: {model name: {group number: name}} from Ecopath's basic_estimates.csv.
  ecopath?: {
    files: number;
    models: string[];
    groups?: Record<string, Record<string, string>>;
    group_conflicts?: string[];
    // {model name: {group number: Ecopath B}} -- the biomass Ecosim starts from.
    baseline_biomass?: Record<string, Record<string, number>>;
    baseline_conflicts?: string[];
  };
  ecosim?: { files: number; models: string[]; scenarios: string[] };
  ecospace?: { files: number; maps?: number; models: string[]; scenarios: string[] };
  ecopath_model?: { files: number; names: string[] };
  ecosim_timeseries?: { files: number; series: number };
  ecospace_maps?: { files: number; shapefiles: number };
  driver_trends?: { files: number };
  not_checked: number;
  /** Version of the identification that produced this (see IDENTIFY_VERSION, backend model_origin.py). */
  version?: number;
}

/** 422 detail from GET /spatial/raster/{id} when a map's coordinates can't be
 * in the CRS it is taken to be in (e.g. metres declared as WGS 84 degrees). */
export interface MapCrsMismatch {
  code: "map_crs_mismatch";
  message: string;
  source_id: string | null;
  source_name: string | null;
  crs: string;
  bounds: [number, number, number, number];
  // Shortlist to choose from, each with the [west, south, east, north] extent
  // in degrees it would give (null = can't be placed on the globe).
  candidates: { crs: string; name: string; extent: [number, number, number, number] | null }[];
}

export interface BrowseEntry {
  name: string;
  path: string;
  looks_like_source: boolean;
}

export interface BrowseResult {
  path: string;
  parent: string | null;
  entries: BrowseEntry[];
  is_drives_list: boolean;
}
