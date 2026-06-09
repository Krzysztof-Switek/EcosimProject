import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { VariableEntry } from "../../api/types";
import { ComparisonChart } from "./ComparisonChart";
import { buildChartModel } from "./transform";

interface Props {
  variable: string;
  freq: "annual" | "monthly";
  entry: VariableEntry;
  label: string;
  scenarios: string[];
  groups: string[];
  fleets: string[];
  yearFrom: number;
  yearTo: number;
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
  groups,
  fleets,
  yearFrom,
  yearTo,
  onRemove,
}: Props) {
  const hasGroups = entry.n_groups > 0;
  const hasFleets = entry.n_fleets > 0;
  const ready = scenarios.length > 0 && (!hasGroups || groups.length > 0);

  const { data, loading, error } = useAsync(
    () =>
      ready
        ? api.timeseries({
            variable,
            freq,
            scenario: scenarios,
            group: hasGroups ? groups : undefined,
            fleet: hasFleets ? fleets : undefined,
            year_from: yearFrom,
            year_to: yearTo,
          })
        : Promise.resolve({ count: 0, variable, freq, rows: [] }),
    [variable, freq, scenarios, groups, fleets, yearFrom, yearTo, ready],
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
          Select scenarios{hasGroups ? " and groups" : ""} to plot this variable.
        </div>
      )}
      {!error && !loading && ready && rows.length === 0 && (
        <div className="muted pad">No data for this selection.</div>
      )}
      {!error && !loading && ready && rows.length > 0 && (
        <ComparisonChart
          model={buildChartModel(rows)}
          yLabel={entry.label ?? variable}
          height={260}
        />
      )}
    </div>
  );
}
