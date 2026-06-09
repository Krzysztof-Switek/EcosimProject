import { useMemo, useState } from "react";
import type { DimItem } from "../../api/types";
import type { VariableKey } from "../catalog/catalogIndex";
import { MultiSelect, type Option } from "../../components/MultiSelect";
import { VariableChart } from "./VariableChart";

interface Props {
  variables: VariableKey[]; // selected, already in the active freq
  freq: "annual" | "monthly";
  scenarioLabels: Record<string, string>;
  groups: DimItem[];
  fleets: DimItem[];
  onRemove: (varId: string) => void;
  onClear: () => void;
}

const varId = (v: { domain: string; variable: string }) => `${v.domain}|${v.variable}`;

/**
 * Shared analysis workspace: one set of controls (scenarios / groups / fleets /
 * year range) drives a grid of per-variable charts, and the whole selection is
 * also the "basket" (manifest) that will feed R analyses.
 */
export function AnalysisView({
  variables,
  freq,
  scenarioLabels,
  groups,
  fleets,
  onRemove,
  onClear,
}: Props) {
  const allScenarios = useMemo(() => {
    const s = new Set<string>();
    for (const v of variables) v.scenarios.forEach((x) => s.add(x));
    return [...s].sort();
  }, [variables]);

  const anyGroups = variables.some((v) => v.entry.n_groups > 0);
  const anyFleets = variables.some((v) => v.entry.n_fleets > 0);
  const yearMin = Math.min(...variables.map((v) => v.entry.year_min));
  const yearMax = Math.max(...variables.map((v) => v.entry.year_max));

  const [selScenarios, setSelScenarios] = useState<string[]>(() => allScenarios.slice(0, 2));
  const [selGroups, setSelGroups] = useState<string[]>(() =>
    anyGroups && groups.length ? [groups[0].name] : [],
  );
  const [selFleets, setSelFleets] = useState<string[]>([]);
  const [yearFrom, setYearFrom] = useState(yearMin);
  const [yearTo, setYearTo] = useState(yearMax);

  const scenarioOpts: Option[] = allScenarios.map((s) => ({
    value: s,
    label: scenarioLabels[s] ?? s,
  }));
  const groupOpts: Option[] = groups.map((g) => ({ value: g.name, label: g.name }));
  const fleetOpts: Option[] = fleets.map((f) => ({ value: f.name, label: f.name }));

  const manifest = {
    freq,
    variables: variables.map((v) => v.variable),
    scenarios: selScenarios,
    groups: anyGroups ? selGroups : [],
    fleets: anyFleets ? selFleets : [],
    year_from: yearFrom,
    year_to: yearTo,
  };

  const copyManifest = () => {
    void navigator.clipboard?.writeText(JSON.stringify(manifest, null, 2));
  };

  return (
    <div className="analysis">
      <aside className="analysis__controls">
        <MultiSelect
          title="Scenarios"
          options={scenarioOpts}
          selected={selScenarios}
          onChange={setSelScenarios}
        />
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
          <label>Year range</label>
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
            {variables.map((v) => (
              <span key={v.key} className="chip">
                {v.label}
                <button className="chip__x" title="Remove" onClick={() => onRemove(varId(v))}>
                  ✕
                </button>
              </span>
            ))}
          </div>
        </div>

        <div className="analysis__grid">
          {variables.map((v) => (
            <VariableChart
              key={v.key}
              variable={v.variable}
              freq={freq}
              entry={v.entry}
              label={v.label}
              scenarios={selScenarios}
              groups={selGroups}
              fleets={selFleets}
              yearFrom={yearFrom}
              yearTo={yearTo}
              onRemove={() => onRemove(varId(v))}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
