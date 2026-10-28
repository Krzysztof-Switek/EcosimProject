import type { DimensionKind, TimeseriesRow } from "../../api/types";

export interface Series {
  key: string;
  label: string;
  color: string;
}

export interface ChartModel {
  series: Series[];
  data: Record<string, number | string | null>[];
  xField: "year" | "date";
}

// Colour-blind-friendly categorical palette.
const PALETTE = [
  "#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2",
  "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
  "#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#8c564b",
];

/** A group's or fleet's display label: EwE's own name where the file carried one,
 * else its number -- most EwE outputs (e.g. catch_annual.csv) have numbers only. */
export function dimensionLabel(kind: DimensionKind, id: number | null, name: string | null): string | null {
  if (name) return name;
  if (id == null) return null;
  return `${kind === "group" ? "Group" : "Fleet"} ${id}`;
}

/**
 * Pivot tidy rows into Recharts-ready data. A series is the combination of the
 * dimensions that actually vary (scenario and/or group), so labels stay terse.
 */
export function buildChartModel(
  rows: TimeseriesRow[],
  scenarioLabel: (scenario: string) => string = (s) => s,
): ChartModel {
  const xField: "year" | "date" =
    rows.length > 0 && rows[0].freq === "monthly" ? "date" : "year";

  const group = (r: TimeseriesRow) => dimensionLabel("group", r.group_id, r.group_name);
  const fleet = (r: TimeseriesRow) => dimensionLabel("fleet", r.fleet_id, r.fleet_name);
  const scenarios = new Set(rows.map((r) => r.scenario));
  const groups = new Set(rows.map(group).filter((g) => g));
  const fleets = new Set(rows.map(fleet).filter((f) => f));
  const multiScenario = scenarios.size > 1;
  const multiGroup = groups.size > 1;
  const multiFleet = fleets.size > 1;

  const seriesKey = (r: TimeseriesRow): string => {
    const g = group(r);
    const f = fleet(r);
    const parts: string[] = [];
    if (multiScenario) parts.push(scenarioLabel(r.scenario));
    if (multiFleet && f) parts.push(f);
    if (multiGroup && g) parts.push(g);
    if (parts.length === 0) parts.push(g ?? f ?? scenarioLabel(r.scenario));
    return parts.join(" · ");
  };

  const seriesOrder: string[] = [];
  const byX = new Map<string | number, Record<string, number | string | null>>();

  for (const r of rows) {
    const key = seriesKey(r);
    if (!seriesOrder.includes(key)) seriesOrder.push(key);
    const x = r[xField];
    let bucket = byX.get(x);
    if (!bucket) {
      bucket = { [xField]: x };
      byX.set(x, bucket);
    }
    bucket[key] = r.value;
  }

  const data = [...byX.values()].sort((a, b) =>
    String(a[xField]).localeCompare(String(b[xField]), undefined, { numeric: true }),
  );

  const series = seriesOrder.map((key, i) => ({
    key,
    label: key,
    color: PALETTE[i % PALETTE.length],
  }));

  return { series, data, xField };
}
