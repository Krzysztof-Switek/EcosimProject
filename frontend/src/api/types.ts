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
