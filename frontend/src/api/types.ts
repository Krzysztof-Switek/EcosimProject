// Shapes returned by the FastAPI backend (see backend/ecosim/api).

export interface ScenarioSummary {
  scenario: string; // slug id
  label: string | null; // authoritative EcosimScenario name (output)
  domain: string;
  n_datasets: number;
  year_min: number;
  year_max: number;
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
  domains: DomainNode[];
}

export interface DimItem {
  id: number;
  name: string;
  slug: string;
}

export interface TimeseriesRow {
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
