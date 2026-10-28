import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { VariableEntry } from "../../api/types";
import { ComparisonChart } from "./ComparisonChart";
import { buildChartModel } from "./transform";

export interface Range {
  year_from?: number;
  year_to?: number;
  month_from?: number;
  month_to?: number;
}

interface Props {
  variable: string;
  freq: "annual" | "monthly";
  entry: VariableEntry;
  label: string;
  scenarios: string[];
  scenarioLabel: (scenario: string) => string;
  groupIds: number[]; // EwE group numbers chosen in step 5
  fleetIds: number[]; // EwE fleet numbers chosen in step 6
  range: Range;
  onRemove: () => void;
}

/**
 * One comparison chart for a single variable, driven by the shared analysis
 * selection. Group/fleet filters are applied only if the variable has that
 * dimension (so indicators and drivers still render a line per scenario).
 */
export function VariableChart({
  variable,
  freq,
  entry,
  label,
  scenarios,
  scenarioLabel,
  groupIds,
  fleetIds,
  range,
  onRemove,
}: Props) {
  const hasGroups = entry.n_groups > 0;
  const hasFleets = entry.n_fleets > 0;
  const ready =
    scenarios.length > 0 && (!hasGroups || groupIds.length > 0) && (!hasFleets || fleetIds.length > 0);
  const missing = [hasGroups && "groups (step 5)", hasFleets && "fleets (step 6)"].filter(Boolean).join(" and ");

  const { data, loading, error } = useAsync(
    () =>
      ready
        ? api.timeseries({
            variable,
            freq,
            scenario: scenarios,
            group_id: hasGroups ? groupIds : undefined,
            fleet_id: hasFleets ? fleetIds : undefined,
            ...range,
          })
        : Promise.resolve({ count: 0, variable, freq, rows: [] }),
    [variable, freq, scenarios.join("|"), groupIds.join("|"), fleetIds.join("|"),
     range.year_from, range.year_to, range.month_from, range.month_to, ready],
  );

  const rows = data?.rows ?? [];

  return (
    <div className="vchart">
      <div className="vchart__head">
        <span className="vchart__title">{label}</span>
        <span className="vchart__meta muted">
          {variable} · {rows.length} pts
        </span>
        <button className="vchart__remove" title="Remove" onClick={onRemove}>
          ✕
        </button>
      </div>
      {error && <div className="error">Error: {error}</div>}
      {!error && loading && <div className="muted pad">Loading…</div>}
      {!error && !loading && !ready && (
        <div className="muted pad">
          Pick models/scenarios{missing ? ` and ${missing}` : ""} to plot this variable.
        </div>
      )}
      {!error && !loading && ready && rows.length === 0 && (
        <div className="muted pad">No data for this selection.</div>
      )}
      {!error && !loading && ready && rows.length > 0 && (
        <ComparisonChart
          model={buildChartModel(rows, scenarioLabel)}
          yLabel={entry.label ?? variable}
          height={260}
        />
      )}
    </div>
  );
}
