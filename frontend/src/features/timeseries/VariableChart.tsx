import { useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { Picks, VariableEntry } from "../../api/types";
import { ComparisonChart } from "./ComparisonChart";
import { buildChartModel, type BaselineMode } from "./transform";

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
  /** Its box's selection (step 5); undefined for a box without one. */
  picks: Picks | undefined;
  box?: string; // the box's title, for the "pick …" hint
  /** Monte Carlo: one run; undefined = baseline + the samples' 5–95% band. */
  run?: string;
  range: Range;
  onRemove: () => void;
}

/**
 * One comparison chart for a single variable, driven by the shared analysis
 * selection. Its box's selection filters it only if the box has one (so
 * indicators and drivers still render a line per scenario).
 */
export function VariableChart({
  variable,
  freq,
  entry,
  label,
  scenarios,
  scenarioLabel,
  picks,
  box,
  run,
  range,
  onRemove,
}: Props) {
  const ready = scenarios.length > 0 && (picks === undefined || picks.length > 0);
  const missing = picks !== undefined && picks.length === 0 ? `its selection in "${box ?? "its box"}" (step 5)` : "";

  const { data, loading, error } = useAsync(
    () =>
      ready
        ? api.timeseries({ variable, freq, scenario: scenarios, picks, run, ...range })
        : Promise.resolve({ count: 0, variable, freq, rows: [] }),
    [variable, freq, scenarios.join("|"), JSON.stringify(picks ?? null), run,
     range.year_from, range.year_to, range.month_from, range.month_to, ready],
  );

  const rows = data?.rows ?? [];
  // Biomass rows carry their group's Ecopath B (backend catalog/service.py) --
  // offered only when it is known for the plotted groups.
  const [baselineMode, setBaselineMode] = useState<BaselineMode>("off");
  const hasBaseline = rows.some((r) => r.baseline != null);
  const mode: BaselineMode = hasBaseline ? baselineMode : "off";

  return (
    <div className="vchart">
      <div className="vchart__head">
        <span className="vchart__title">{label}</span>
        <span className="vchart__meta muted">
          {variable} · {rows.length} pts
          {rows[0]?.n_samples ? ` · band: 5–95% of ${rows[0].n_samples} samples` : ""}
        </span>
        {hasBaseline && (
          <label className="vchart__baseline" title="Ecopath biomass B of each group -- the state Ecosim starts from">
            Ecopath baseline
            <select value={baselineMode} onChange={(e) => setBaselineMode(e.target.value as BaselineMode)}>
              <option value="off">Off</option>
              <option value="line">Line (B0)</option>
              <option value="relative">Relative (B / B0)</option>
            </select>
          </label>
        )}
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
          model={buildChartModel(rows, scenarioLabel, mode)}
          yLabel={mode === "relative" ? `${entry.label ?? variable} / Ecopath B0` : entry.label ?? variable}
          height={260}
          referenceY={mode === "relative" ? { y: 1, label: "Ecopath state" } : undefined}
        />
      )}
    </div>
  );
}
