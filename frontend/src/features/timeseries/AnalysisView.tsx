import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { Picks } from "../../api/types";
import type { VariableKey } from "../catalog/catalogIndex";
import { CATEGORY_LABELS } from "../catalog/categories";
import { SelectionStep } from "../catalog/SelectionStep";
import type { BoxSelection } from "../catalog/useBoxSelections";
import { VariableChart } from "./VariableChart";
import { SaveResults } from "./SaveResults";
import { AnalysisPanel } from "../analyses/AnalysisPanel";
import { MapSeriesSection } from "../areas/MapSeriesSection";

interface Props {
  variables: VariableKey[]; // selected, already in the active freq
  freq: "annual" | "monthly";
  scenarioLabel: (scenario: string) => string;
  scenariosForVar: (v: VariableKey) => string[]; // the series of steps 1–2 that offer it
  /** Step 5: each Results-Extractor box's selection (shown for boxes with checked variables). */
  boxes: BoxSelection[];
  /** The selection of a variable's Results-Extractor box (step 5); undefined
   * for a variable whose box has none (indicators, fitting statistics, drivers). */
  picksFor: (v: VariableKey) => Picks | undefined;
  describePicks: (v: VariableKey) => string;
  onRemove: (varId: string) => void;
  onClear: () => void;
}

const varId = (v: { domain: string; variable: string }) => `${v.domain}|${v.variable}`;

// English month names (the UI is English-only; avoids the browser's localised
// <input type="month"> widget, which also shows a confusing year).
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/**
 * Shared analysis workspace. The controls column, right next to the sidebar,
 * holds step 5 -- the selection of each Results-Extractor box with checked
 * variables -- then the range control; both drive the whole grid. The range
 * control follows the time step (step 3): years for annual, months for monthly.
 * Below it, "Save results" downloads the selection as CSV, like the EwE Results
 * Extractor. The selection is also the "basket" (manifest) that feeds R analyses.
 * Charts only visualise the chosen data — no computation happens here.
 */
export function AnalysisView({
  variables,
  freq,
  scenarioLabel,
  scenariosForVar,
  boxes,
  picksFor,
  describePicks,
  onRemove,
  onClear,
}: Props) {
  const monthly = freq === "monthly";
  const yearMin = Math.min(...variables.map((v) => v.entry.year_min));
  const yearMax = Math.max(...variables.map((v) => v.entry.year_max));

  // Range bounds default to the full available span (a filter window, not a
  // data selection); unit follows the time step — years for annual, months
  // (1–12, month-of-year) for monthly.
  const [yearFrom, setYearFrom] = useState(yearMin);
  const [yearTo, setYearTo] = useState(yearMax);
  const [monthFrom, setMonthFrom] = useState(1);
  const [monthTo, setMonthTo] = useState(12);

  // Monte Carlo runs of the plotted scenarios; "" = baseline + the samples'
  // 5–95% band (the manual's way of showing them, UG p.180 Fig. 10).
  const scenarioKey = [...new Set(variables.flatMap((v) => scenariosForVar(v)))].sort().join("|");
  const runs = useAsync(
    () => (scenarioKey ? api.runs(scenarioKey.split("|")) : Promise.resolve([])),
    [scenarioKey],
  );
  const runList = runs.data ?? [];
  const [run, setRun] = useState("");
  useEffect(() => {
    if (run && !runList.some((r) => r.run_id === run)) setRun("");
  }, [runList, run]);
  const nSamples = runList.filter((r) => r.kind === "sample").length;
  const baselineLabel = runList.find((r) => r.kind === "baseline")?.label ?? runList.find((r) => r.kind === "main")?.label;

  // Range params forwarded to the API, depending on the time step.
  const range = monthly
    ? { month_from: monthFrom, month_to: monthTo }
    : { year_from: yearFrom, year_to: yearTo };

  // Each variable carries its own box selection (`picks`, see query_timeseries).
  const picksKey = JSON.stringify(variables.map((v) => picksFor(v) ?? null));
  const manifest = useMemo(
    () => ({
      freq,
      ...(run ? { run } : {}),
      ...range,
      variables: variables.map((v) => ({
        variable: v.variable,
        domain: v.domain,
        scenarios: scenariosForVar(v),
        ...(picksFor(v) ? { picks: picksFor(v) } : {}),
      })),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [freq, run, picksKey, yearFrom, yearTo, monthFrom, monthTo, variables, scenariosForVar],
  );

  const copyManifest = () => {
    void navigator.clipboard?.writeText(JSON.stringify(manifest, null, 2));
  };

  // Step-5 boxes the user folded away (all open by default).
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggleBox = (box: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(box) ? next.delete(box) : next.add(box);
      return next;
    });

  // Checked variables whose box has no selection window -- in EwE, Indicators and
  // Fitting statistics have no "Change Selection" (one value for the whole
  // ecosystem or model); shown in step 5 all the same, so it never looks empty.
  const unselectable = new Map<string, VariableKey[]>();
  for (const v of variables) {
    if (picksFor(v) !== undefined) continue;
    const title =
      v.domain === "input" ? "Drivers (inputs)" : (v.category && CATEGORY_LABELS[v.category]) || "Other model outputs";
    unselectable.set(title, [...(unselectable.get(title) ?? []), v]);
  }
  const noScenarios = variables.every((v) => scenariosForVar(v).length === 0);

  return (
    <div className="analysis">
      <aside className="analysis__controls">
        {noScenarios && (
          <div className="selbox__note">
            Pick a model and its scenarios (steps 1–2) to plot and save these variables.
          </div>
        )}
        {[...unselectable].map(([title, vars]) => (
          <div key={title} className="step selbox__none">
            <div className="step__head">
              <span className="step__n">5</span>
              <span className="step__title">{title}</span>
            </div>
            <div className="step__body">
              <div className="selbox__for muted">For: {vars.map((v) => v.label).join(", ")}</div>
              <div className="muted selbox__explain">
                No selection needed: one series per scenario for the whole ecosystem — as in the
                EwE Results Extractor, this box has no group or fleet selection.
              </div>
            </div>
          </div>
        ))}
        {boxes
          .filter((b) => b.variables.length > 0)
          .map((b) => (
            <SelectionStep
              key={b.box}
              n={5}
              sel={b}
              open={!collapsed.has(b.box)}
              onToggle={() => toggleBox(b.box)}
            />
          ))}
        {runList.length > 0 && (
          <div className="field">
            <label>Monte Carlo runs</label>
            <select className="mcrun" value={run} onChange={(e) => setRun(e.target.value)}>
              <option value="">
                {baselineLabel ?? "Baseline"} + 5–95% band of {nSamples} samples
              </option>
              {runList.map((r) => (
                <option key={`${r.scenario}|${r.run_id}`} value={r.run_id}>
                  Only {r.label}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label>{monthly ? "Month range" : "Year range"}</label>
          {monthly ? (
            <div className="row">
              <select value={monthFrom} onChange={(e) => setMonthFrom(Number(e.target.value))}>
                {MONTHS.map((m, i) => (
                  <option key={m} value={i + 1}>
                    {m}
                  </option>
                ))}
              </select>
              <span>–</span>
              <select value={monthTo} onChange={(e) => setMonthTo(Number(e.target.value))}>
                {MONTHS.map((m, i) => (
                  <option key={m} value={i + 1}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div className="row">
              <input
                type="number"
                value={yearFrom}
                min={yearMin}
                max={yearMax}
                onChange={(e) => setYearFrom(Number(e.target.value))}
              />
              <span>–</span>
              <input
                type="number"
                value={yearTo}
                min={yearMin}
                max={yearMax}
                onChange={(e) => setYearTo(Number(e.target.value))}
              />
            </div>
          )}
        </div>
        <SaveResults
          variables={variables}
          freq={freq}
          range={range}
          run={run || undefined}
          scenariosFor={scenariosForVar}
          picksFor={picksFor}
          describe={describePicks}
        />
      </aside>

      <section className="analysis__main">
        <div className="basket">
          <div className="basket__head">
            <strong>Selection</strong>
            <span className="muted">
              {variables.length} variable{variables.length === 1 ? "" : "s"} · {freq} · ready for R analysis
            </span>
            <div className="basket__actions">
              <button className="btn btn--ghost" onClick={copyManifest}>
                Copy manifest (JSON)
              </button>
              <button className="btn btn--ghost" onClick={onClear}>
                Clear all
              </button>
            </div>
          </div>
          <div className="basket__chips">
            {variables.map((v) => {
              const id = varId(v);
              return (
                <span key={v.key} className="chip">
                  {v.label}
                  <button
                    className="chip__x"
                    title="Remove"
                    onClick={() => onRemove(id)}
                  >
                    ✕
                  </button>
                </span>
              );
            })}
          </div>

          <AnalysisPanel manifest={manifest} variableNames={variables.map((v) => v.variable)} />
        </div>

        <MapSeriesSection
          scenarios={scenarioKey ? scenarioKey.split("|") : []}
          scenarioLabel={scenarioLabel}
          yearFrom={monthly ? null : yearFrom}
          yearTo={monthly ? null : yearTo}
          run={run}
          preferVariables={variables.map((v) => v.variable)}
        />

        <div className="analysis__grid">
          {variables.map((v) => (
            <VariableChart
              key={v.key}
              variable={v.variable}
              freq={freq}
              entry={v.entry}
              label={v.label}
              scenarios={scenariosForVar(v)}
              scenarioLabel={scenarioLabel}
              picks={picksFor(v)}
              box={v.category ? CATEGORY_LABELS[v.category] : undefined}
              run={run || undefined}
              range={range}
              onRemove={() => onRemove(varId(v))}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
