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
  /** Monte Carlo summary rows: `value` is the baseline run's, these the samples'
   * 5th/95th percentile and how many samples there were. */
  p05?: number | null;
  p95?: number | null;
  n_samples?: number;
}

/** One Monte Carlo / Ecosampler run of a scenario (GET /catalog/runs). */
export interface RunEntry {
  scenario: string;
  run_id: string;
  kind: "baseline" | "main" | "sample";
  label: string;
}

/** One entry of a Results-Extractor box's selection window (GET /catalog/selection):
 * a functional group or fleet present in the data of the box's checked variables.
 * `key` is what `picks` take; `id`/`name` are EwE's number and name -- most output
 * files carry only the number, predation/prey files only the name, and each is
 * completed from the model's Ecopath output where it is loaded. */
export interface SelectionEntity {
  key: string;
  id: number | null;
  name: string | null;
  variables: string[]; // which of the requested variables contain it
  /** "Attached" boxes: this entity's partners (e.g. a predator's prey). */
  children?: SelectionEntity[];
}

/** A box selection as /timeseries takes it: [parent] or [parent, partner] keys. */
export type Picks = string[][];

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
  /** Monte Carlo maps: how many runs (0 for ordinary maps). */
  n_runs: number;
  /** The same variable's time-series label, if it has one (e.g. "Total B (ECOIND)"). */
  label: string | null;
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
  run_id: string | null;
}

export interface AnalysisParam {
  key: string;
  type: "number" | "bool" | "choice" | string;
  default: unknown;
  label: string | null;
  /** type "choice": the allowed values. */
  choices?: string[] | null;
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
  /** A .zip file -- listed only when browsing with ``zip`` (region packs). */
  is_file?: boolean;
}

export interface BrowseResult {
  path: string;
  parent: string | null;
  entries: BrowseEntry[];
  is_drives_list: boolean;
}

/** A region layer (ICES subdivisions/rectangles, a management mask) on one
 * model grid -- backend regions/store.py. */
export interface RegionClass {
  id: number;
  code: string;
  label: string;
  cells: number;
}

export interface RegionGrid {
  ncols: number;
  nrows: number;
  xll: number;
  yll: number;
  cellsize: number;
}

export interface RegionLayer {
  id: string;
  pack_id: string;
  /** Grid-independent identity, e.g. "ices_subdivisions" -- what a saved area refers to. */
  key: string;
  kind: "regions" | "mask";
  title: string;
  category: "ICES" | "Management" | "Other";
  grid: RegionGrid;
  crs: string;
  classes: RegionClass[];
  details: Record<string, string>;
}

export interface RegionPack {
  id: string;
  name: string;
  source_path: string;
  imported_at: string;
  warnings: string[];
  layers: RegionLayer[];
}

/** One part of an area: picked regions of a layer (no codes = all of them, or a 0/1 mask), or a drawn polygon. */
export type AreaItem =
  | { kind: "regions"; layer: string; codes?: string[] }
  | { kind: "drawn"; geojson: GeoJSON.FeatureCollection };

/** Items in a group are joined (union); groups are intersected -- backend regions/masks.py. */
export interface AreaDefinition {
  groups: AreaItem[][];
}

export interface SavedArea {
  id: string;
  name: string;
  area: AreaDefinition;
}

export interface AreaLibrary {
  areas: SavedArea[];
  selected: string[];
  /** False until first written -- areas from the old browser storage are moved in then. */
  saved: boolean;
}

/** How the model's grid was matched to the loaded reference areas. */
export interface DataGridInfo {
  status: "matched" | "no_match" | "unknown";
  message: string | null;
  grid: RegionGrid | null;
  crs: string | null;
}

export interface RegionLayersForGrid {
  grid: DataGridInfo | null;
  layers: RegionLayer[];
}

export interface AreaSummary {
  cells: number;
  area_km2: number;
  geojson?: GeoJSON.FeatureCollection;
  grid: DataGridInfo;
}

export interface AuthStatus {
  /** Whether this server needs signing in. */
  enabled: boolean;
  user: string | null;
  /** "admin" can change data sources and reference areas; "tester" only uses them. */
  role: "admin" | "tester" | null;
}

/** One area x group/fleet x year of a zonal summary (backend regions/zonal.py). */
export interface ZonalRow {
  area_id: string;
  entity: string | null;
  year: number;
  /** Area-weighted mean over the area's cells that have a value. */
  mean: number | null;
  /** Sum of value x cell area (km²) -- only for densities (biomass, catch, effort...). */
  total?: number | null;
  min?: number | null;
  max?: number | null;
  n_cells: number;
  /** Share of the area's cells that have a value in the model's map. */
  coverage: number | null;
  mean_p05?: number | null;
  mean_p95?: number | null;
  total_p05?: number | null;
  total_p95?: number | null;
  n_samples?: number;
}

export interface ZonalResult {
  variable: string;
  semantics: "density" | "fraction" | "indicator";
  run: string | null;
  areas: { id: string; name: string; cells: number; area_km2: number }[];
  rows: ZonalRow[];
  maps: number;
  maps_missing: number;
  problems?: string[];
  cancelled?: boolean;
}

export interface ZonalCost {
  maps: number;
  maps_cached: number;
  maps_to_read: number;
  maps_to_download: number;
  bytes_to_download: number;
  seconds_estimate: number;
  /** The sync app (e.g. OneDrive) the downloads need isn't running -- they would be left out. */
  sync_app_missing: string | null;
}

export interface ZonalJob {
  id: string;
  status: "running" | "done" | "cancelled" | "error";
  phase: "starting" | "downloading" | "reading" | "done";
  done: number;
  total: number;
  /** The sync app stopped serving files; waiting for it to come back. */
  paused: boolean;
  error: string | null;
  result: ZonalResult | null;
}

export type ZonalResponse =
  | { status: "done"; result: ZonalResult }
  | { status: "confirm"; cost: ZonalCost }
  | { status: "running"; job: ZonalJob };

export interface ZonalRequest {
  scenario: string;
  variable: string;
  areas: SavedArea[];
  domain?: string;
  entities?: string[];
  year_from?: number;
  year_to?: number;
  /** A run_id, "all" (Monte Carlo: baseline + 5-95% band) or omitted (the baseline run). */
  run?: string;
  start?: boolean;
}
