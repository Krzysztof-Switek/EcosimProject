import { useMemo, useState } from "react";
import type { ModelSummary } from "../../api/types";
import { Step } from "../../components/Step";
import type { VariableKey } from "./catalogIndex";
import { CATEGORY_ORDER, CATEGORY_LABELS } from "./categories";

type Freq = "annual" | "monthly";

interface Props {
  models: ModelSummary[];
  variables: VariableKey[]; // already filtered to the active freq by App
  freq: Freq;
  onFreqChange: (f: Freq) => void;

  // Step 1 — models
  selectedModels: Set<string>;
  onToggleModel: (model: string) => void;

  // Step 2 — scenarios (output, grouped under their model)
  selectedScenarios: Set<string>;
  onToggleScenario: (scenario: string) => void;
  onSetModelScenarios: (scenarios: string[], on: boolean) => void;

  // Step 4 — variables
  selectedVarIds: Set<string>;
  onToggleVar: (id: string) => void;
  focusedVarId: string | null;
  onFocusVar: (id: string) => void;
  effectiveScenarios: (v: VariableKey) => string[];
}

const varId = (v: VariableKey) => `${v.domain}|${v.variable}`;

interface Section {
  id: string;
  title: string;
  items: VariableKey[];
}

/** Output variables grouped by Results-Extractor category, drivers last. */
function buildSections(variables: VariableKey[]): Section[] {
  const byCategory = new Map<string, VariableKey[]>();
  const drivers: VariableKey[] = [];
  const other: VariableKey[] = [];

  for (const v of variables) {
    if (v.domain === "input") {
      drivers.push(v);
    } else if (v.category && CATEGORY_LABELS[v.category]) {
      const arr = byCategory.get(v.category) ?? [];
      arr.push(v);
      byCategory.set(v.category, arr);
    } else {
      other.push(v);
    }
  }

  const sections: Section[] = [];
  for (const cat of CATEGORY_ORDER) {
    const items = byCategory.get(cat.id);
    if (items && items.length) sections.push({ id: cat.id, title: cat.label, items });
  }
  if (other.length) sections.push({ id: "other", title: "Other model outputs", items: other });
  if (drivers.length) sections.push({ id: "input", title: "Drivers (inputs)", items: drivers });
  return sections;
}

/**
 * Left-hand guided navigator:
 *   1. Models → 2. Scenarios → 3. Frequency → 4. Variables
 * Steps 1–2 define the global pool of (model, scenario) series; clicking a
 * variable focuses it, and its per-variable model/scenario picker is shown
 * (always visible) at the top of the analysis controls column.
 */
export function Sidebar(props: Props) {
  const {
    models,
    variables,
    freq,
    onFreqChange,
    selectedModels,
    onToggleModel,
    selectedScenarios,
    onToggleScenario,
    onSetModelScenarios,
    selectedVarIds,
    onToggleVar,
    focusedVarId,
    onFocusVar,
    effectiveScenarios,
  } = props;

  const [filter, setFilter] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set()); // step ids collapsed
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set());

  const isStepOpen = (id: string) => !collapsed.has(id);
  const toggleStep = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const sections = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const visible = f
      ? variables.filter((v) => v.label.toLowerCase().includes(f) || v.variable.includes(f))
      : variables;
    return buildSections(visible);
  }, [variables, filter]);

  const filtering = filter.trim().length > 0;
  const isCatOpen = (id: string) => filtering || expandedCats.has(id);
  const toggleCat = (id: string) =>
    setExpandedCats((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  // Scenarios visible in step 2: only those belonging to the selected models.
  const activeModels = models.filter((m) => selectedModels.has(m.model));

  return (
    <nav className="sidebar">
      {/* Step 1 — Models */}
      <Step
        n={1}
        title="Models"
        hint={`${selectedModels.size}/${models.length}`}
        open={isStepOpen("models")}
        onToggle={() => toggleStep("models")}
      >
        {models.map((m) => (
          <label key={m.model} className="picker__item">
            <input
              type="checkbox"
              checked={selectedModels.has(m.model)}
              onChange={() => onToggleModel(m.model)}
            />
            <span className="picker__label">{m.model_name}</span>
            <span className="badge badge--muted">{m.scenarios.length} scen.</span>
          </label>
        ))}
        {models.length === 0 && <div className="muted pad">no models</div>}
      </Step>

      {/* Step 2 — Scenarios (grouped by model) */}
      <Step
        n={2}
        title="Scenarios"
        hint={`${selectedScenarios.size} selected`}
        open={isStepOpen("scenarios")}
        onToggle={() => toggleStep("scenarios")}
      >
        {activeModels.length === 0 && <div className="muted pad">select a model first</div>}
        {activeModels.map((m) => {
          const ids = m.scenarios.map((s) => s.scenario);
          const allOn = ids.every((id) => selectedScenarios.has(id));
          return (
            <div key={m.model} className="picker__group">
              <div className="picker__group-head">
                <span className="picker__group-title">{m.model_name}</span>
                <button className="linkbtn" onClick={() => onSetModelScenarios(ids, !allOn)}>
                  {allOn ? "none" : "all"}
                </button>
              </div>
              {m.scenarios.map((s) => (
                <label key={s.scenario} className="picker__item picker__item--indent">
                  <input
                    type="checkbox"
                    checked={selectedScenarios.has(s.scenario)}
                    onChange={() => onToggleScenario(s.scenario)}
                  />
                  <span className="picker__label">{s.label}</span>
                </label>
              ))}
            </div>
          );
        })}
      </Step>

      {/* Step 3 — Time step */}
      <div className="step">
        <div className="step__head step__head--static">
          <span className="step__n">3</span>
          <span className="step__title">Time step</span>
        </div>
        <div className="step__body">
          <div className="freqtoggle" role="tablist" aria-label="Frequency">
            <button
              className={`freqtoggle__btn ${freq === "annual" ? "is-active" : ""}`}
              onClick={() => onFreqChange("annual")}
            >
              Annual
            </button>
            <button
              className={`freqtoggle__btn ${freq === "monthly" ? "is-active" : ""}`}
              onClick={() => onFreqChange("monthly")}
            >
              Monthly
            </button>
          </div>
        </div>
      </div>

      {/* Step 4 — Variables */}
      <div className="step step--grow">
        <div className="step__head step__head--static">
          <span className="step__n">4</span>
          <span className="step__title">Variables</span>
          <input
            className="catalog__filter"
            placeholder="filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <div className="catalog__list">
          {sections.map((section) => {
            const open = isCatOpen(section.id);
            return (
              <div key={section.id} className="catalog__group">
                <button
                  className="catalog__group-title catalog__group-title--btn"
                  onClick={() => toggleCat(section.id)}
                >
                  <span className="catalog__chevron">{open ? "▾" : "▸"}</span>
                  <span>{section.title}</span>
                  <span className="catalog__count">{section.items.length}</span>
                </button>
                {open &&
                  section.items.map((v) => {
                    const id = varId(v);
                    const checked = selectedVarIds.has(id);
                    const focused = focusedVarId === id;
                    const eff = checked ? effectiveScenarios(v) : [];
                    return (
                      <div
                        key={v.key}
                        className={`catalog__item ${checked ? "is-active" : ""} ${focused ? "is-focused" : ""}`}
                      >
                        <input
                          type="checkbox"
                          className="catalog__check"
                          checked={checked}
                          onChange={() => onToggleVar(id)}
                        />
                        <span
                          className="catalog__item-label catalog__item-label--btn"
                          onClick={() => onFocusVar(id)}
                          title="Show its models & scenarios in the controls column"
                        >
                          {v.label}
                        </span>
                        <button
                          className={`badge ${checked ? "" : "badge--muted"} badge--btn`}
                          onClick={() => onFocusVar(id)}
                          title="Choose models & scenarios"
                        >
                          {checked ? `${eff.length} series` : `${v.scenarios.length} scen.`}
                        </button>
                      </div>
                    );
                  })}
              </div>
            );
          })}
          {sections.length === 0 && <div className="muted pad">no variables</div>}
        </div>
      </div>
    </nav>
  );
}
