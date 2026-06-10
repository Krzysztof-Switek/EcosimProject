import { useMemo, useState } from "react";
import type { VariableKey } from "./catalogIndex";

interface Props {
  variable: VariableKey;
  scenarioLabel: (scenario: string) => string;
  available: string[]; // scenario ids allowed by steps 1–2 (the only candidates)
  selected: string[]; // currently effective scenario ids
  hasOverride: boolean;
  onChange: (scenarios: string[]) => void;
  onClear: () => void;
}

interface ModelGroup {
  model: string | null;
  model_name: string;
  scenarios: string[]; // scenario ids under this model that offer the variable
}

/**
 * Group the variable's available (model, scenario) combos by model, keeping only
 * scenarios chosen in steps 1–2 (`available`). Models with nothing available are
 * dropped — so a model never selected upstream cannot reappear here.
 */
function groupCombos(variable: VariableKey, available: Set<string>): ModelGroup[] {
  const byModel = new Map<string, ModelGroup>();
  for (const c of variable.combos) {
    if (!available.has(c.scenario)) continue;
    const key = c.model ?? "__drivers__";
    const name = c.model ? c.model_name ?? c.model : "Drivers (inputs)";
    const g = byModel.get(key) ?? { model: c.model, model_name: name, scenarios: [] };
    if (!g.scenarios.includes(c.scenario)) g.scenarios.push(c.scenario);
    byModel.set(key, g);
  }
  return [...byModel.values()];
}

const groupKey = (g: ModelGroup) => g.model ?? "__drivers__";

/**
 * Always-visible picker (docked at the top of the controls column) for the
 * focused variable. Progressive, top-down: only the available models are shown
 * first; a model's scenarios appear when you expand it — so a variable with two
 * models doesn't dump every scenario at once. Nothing is preselected; the user
 * picks the series to plot. Any choice is a per-variable override until
 * "Reset to selected pool" is clicked.
 */
export function VariableSeriesPicker({
  variable,
  scenarioLabel,
  available,
  selected,
  hasOverride,
  onChange,
  onClear,
}: Props) {
  const groups = useMemo(
    () => groupCombos(variable, new Set(available)),
    [variable, available],
  );
  const sel = new Set(selected);

  // Expand models that already have a chosen scenario; others start collapsed.
  // Keyed by variable (parent remounts on focus change), so this re-inits per
  // variable rather than persisting stale expansion.
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(groups.filter((g) => g.scenarios.some((s) => sel.has(s))).map(groupKey)),
  );

  const toggleExpand = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  const toggleScenario = (scenario: string) => {
    const next = new Set(sel);
    next.has(scenario) ? next.delete(scenario) : next.add(scenario);
    onChange([...next]);
  };

  const setModelScenarios = (scenarios: string[], on: boolean) => {
    const next = new Set(sel);
    for (const s of scenarios) on ? next.add(s) : next.delete(s);
    onChange([...next]);
  };

  return (
    <div className="multiselect seriespicker">
      <div className="multiselect__head">
        <span>Models &amp; scenarios</span>
        <span className="muted">{selected.length} selected</span>
      </div>
      <div className="seriespicker__var" title={variable.label}>
        {variable.label}
      </div>
      <div className="multiselect__list">
        {groups.map((g) => {
          const key = groupKey(g);
          const open = expanded.has(key);
          const chosen = g.scenarios.filter((s) => sel.has(s)).length;
          const allOn = chosen === g.scenarios.length && chosen > 0;
          return (
            <div key={key} className="picker__group">
              <button
                className="seriespicker__model"
                onClick={() => toggleExpand(key)}
                title={open ? "Hide scenarios" : "Show scenarios"}
              >
                <span className="catalog__chevron">{open ? "▾" : "▸"}</span>
                <span className="picker__label">{g.model_name}</span>
                <span className={`badge ${chosen ? "" : "badge--muted"}`}>
                  {chosen ? `${chosen}/${g.scenarios.length}` : `${g.scenarios.length} scen.`}
                </span>
              </button>
              {open && (
                <>
                  <div className="seriespicker__modelbar">
                    <button
                      className="linkbtn"
                      onClick={() => setModelScenarios(g.scenarios, !allOn)}
                    >
                      {allOn ? "clear" : "select all"}
                    </button>
                  </div>
                  {g.scenarios.map((s) => (
                    <label key={s} className="picker__item picker__item--indent">
                      <input
                        type="checkbox"
                        checked={sel.has(s)}
                        onChange={() => toggleScenario(s)}
                      />
                      <span className="picker__label">{scenarioLabel(s)}</span>
                    </label>
                  ))}
                </>
              )}
            </div>
          );
        })}
        {groups.length === 0 && (
          <div className="muted pad">Pick models & scenarios in steps 1–2 first.</div>
        )}
      </div>
      <div className="seriespicker__foot">
        <button className="linkbtn" disabled={!hasOverride} onClick={onClear}>
          Clear
        </button>
      </div>
    </div>
  );
}
