import { useMemo, useState } from "react";
import type { DimItem } from "../../api/types";
import type { VariableKey } from "../catalog/catalogIndex";
import { MultiSelect, type Option } from "../../components/MultiSelect";
import { VariableSeriesPicker } from "../catalog/VariableSeriesPicker";
import { VariableChart } from "./VariableChart";
import { AnalysisPanel } from "../analyses/AnalysisPanel";

interface Props {
  variables: VariableKey[]; // selected, already in the active freq
  freq: "annual" | "monthly";
  scenarioLabel: (scenario: string) => string;
  scenariosForVar: (v: VariableKey) => string[]; // effective per-variable series
  availableScenarios: (v: VariableKey) => string[]; // candidates allowed by steps 1–2
  groups: DimItem[];
  fleets: DimItem[];
  onRemove: (varId: string) => void;
  onClear: () => void;

  // Per-variable model/scenario picker (docked top of controls column).
  focusedVariable: VariableKey | null;
  hasOverride: (varId: string) => boolean;
  onSetVarScenarios: (varId: string, scenarios: string[] | null) => void;
  onFocusVar: (varId: string) => void;
}

const varId = (v: { domain: string; variable: string }) => `${v.domain}|${v.variable}`;

// English month names (the UI is English-only; avoids the browser's localised
// <input type="month"> widget, which also shows a confusing year).
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/**
 * Shared analysis workspace. The focused variable's model/scenario picker sits
 * (always visible) at the top of the controls column; group / fleet / range
 * controls below drive the whole grid. The range control follows the time step
 * (step 3): years for annual, year-months for monthly. The selection is also the
 * "basket" (manifest) that feeds R analyses. Charts only visualise the chosen
 * data — no computation happens here.
 */
export function AnalysisView({
  variables,
  freq,
  scenarioLabel,
  scenariosForVar,
  availableScenarios,
  groups,
  fleets,
  onRemove,
  onClear,
  focusedVariable,
  hasOverride,
  onSetVarScenarios,
  onFocusVar,
}: Props) {
  const monthly = freq === "monthly";
  const anyGroups = variables.some((v) => v.entry.n_groups > 0);
  const anyFleets = variables.some((v) => v.entry.n_fleets > 0);
  const yearMin = Math.min(...variables.map((v) => v.entry.year_min));
  const yearMax = Math.max(...variables.map((v) => v.entry.year_max));

  // Nothing preselected: groups/fleets start empty — the user chooses.
  const [selGroups, setSelGroups] = useState<string[]>([]);
  const [selFleets, setSelFleets] = useState<string[]>([]);
  // Range bounds default to the full available span (a filter window, not a
  // data selection); unit follows the time step — years for annual, months
  // (1–12, month-of-year) for monthly.
  const [yearFrom, setYearFrom] = useState(yearMin);
  const [yearTo, setYearTo] = useState(yearMax);
  const [monthFrom, setMonthFrom] = useState(1);
  const [monthTo, setMonthTo] = useState(12);

  const groupOpts: Option[] = groups.map((g) => ({ value: g.name, label: g.name }));
  const fleetOpts: Option[] = fleets.map((f) => ({ value: f.name, label: f.name }));

  // Range params forwarded to the API, depending on the time step.
  const range = monthly
    ? { month_from: monthFrom, month_to: monthTo }
    : { year_from: yearFrom, year_to: yearTo };

  const manifest = useMemo(
    () => ({
      freq,
      groups: anyGroups ? selGroups : [],
      fleets: anyFleets ? selFleets : [],
      ...range,
      variables: variables.map((v) => ({
        variable: v.variable,
        domain: v.domain,
        scenarios: scenariosForVar(v),
      })),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [freq, anyGroups, selGroups, anyFleets, selFleets, yearFrom, yearTo, monthFrom, monthTo, variables, scenariosForVar],
  );

  const copyManifest = () => {
    void navigator.clipboard?.writeText(JSON.stringify(manifest, null, 2));
  };

  const focusedId = focusedVariable ? varId(focusedVariable) : null;

  return (
    <div className="analysis">
      <aside className="analysis__controls">
        {focusedVariable && (
          <VariableSeriesPicker
            key={varId(focusedVariable)}
            variable={focusedVariable}
            scenarioLabel={scenarioLabel}
            available={availableScenarios(focusedVariable)}
            selected={scenariosForVar(focusedVariable)}
            hasOverride={hasOverride(varId(focusedVariable))}
            onChange={(list) => onSetVarScenarios(varId(focusedVariable), list)}
            onClear={() => onSetVarScenarios(varId(focusedVariable), null)}
          />
        )}
        {anyGroups && (
          <MultiSelect
            title="Groups"
            options={groupOpts}
            selected={selGroups}
            onChange={setSelGroups}
            searchable
            collapsible
          />
        )}
        {anyFleets && (
          <MultiSelect
            title="Fleets"
            options={fleetOpts}
            selected={selFleets}
            onChange={setSelFleets}
            searchable
            collapsible
          />
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
                <span
                  key={v.key}
                  className={`chip chip--btn ${focusedId === id ? "is-focused" : ""}`}
                  onClick={() => onFocusVar(id)}
                  title="Edit its models & scenarios"
                >
                  {v.label}
                  <button
                    className="chip__x"
                    title="Remove"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemove(id);
                    }}
                  >
                    ✕
                  </button>
                </span>
              );
            })}
          </div>

          <AnalysisPanel manifest={manifest} variableNames={variables.map((v) => v.variable)} />
        </div>

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
              groups={selGroups}
              fleets={selFleets}
              range={range}
              onRemove={() => onRemove(varId(v))}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
