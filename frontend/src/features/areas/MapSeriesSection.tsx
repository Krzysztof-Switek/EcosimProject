import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { RasterEntry } from "../../api/types";
import { AreaSummaryPanel } from "./AreaSummaryPanel";
import { useAreaLibrary, useAreaShapes } from "./useAreas";

/**
 * Time series of an Ecospace variable within areas -- derived from the maps
 * (Ecosim's own series have no spatial dimension). Uses the view's year range
 * and Monte Carlo choice; the areas are the ones saved in "Spatial data".
 */
export function MapSeriesSection({
  scenarios,
  scenarioLabel,
  yearFrom,
  yearTo,
  run,
  preferVariables = [],
}: {
  /** The scenarios plotted in this view; maps are offered for those that have them. */
  scenarios: string[];
  scenarioLabel: (s: string) => string;
  yearFrom: number | null;
  yearTo: number | null;
  /** The view's Monte Carlo choice: a run_id, or "" for the baseline + band. */
  run: string;
  /** Variables plotted in the view -- the first with maps is picked by default. */
  preferVariables?: string[];
}) {
  const [open, setOpen] = useState(false);
  const layers = useAsync(() => (open ? api.spatialLayers() : Promise.resolve([])), [open]);
  const withMaps = useMemo(
    () => (layers.data ?? []).filter((l) => l.domain === "output" && scenarios.includes(l.scenario)),
    [layers.data, scenarios],
  );
  const mapScenarios = [...new Set(withMaps.map((l) => l.scenario))];

  const [scenario, setScenario] = useState("");
  const [variable, setVariable] = useState("");
  const [entities, setEntities] = useState<string[]>([]);
  const [areaIds, setAreaIds] = useState<string[]>([]);
  useEffect(() => {
    if (mapScenarios.length && !mapScenarios.includes(scenario)) setScenario(mapScenarios[0]);
  }, [mapScenarios, scenario]);
  const variables = withMaps.filter((l) => l.scenario === scenario);
  const layer = variables.find((l) => l.variable === variable) ?? null;
  useEffect(() => {
    if (variables.length && !layer) {
      setVariable((variables.find((l) => preferVariables.includes(l.variable)) ?? variables[0]).variable);
    }
  }, [variables, layer, preferVariables]);

  // Groups/fleets the variable's maps have (from one run's list for Monte Carlo maps).
  const hasEntity = !!layer && (layer.n_groups > 0 || layer.n_fleets > 0);
  const firstRun = useAsync(
    () => (layer && layer.n_runs > 0 ? api.spatialRuns({ scenario, variable }) : Promise.resolve([])),
    [scenario, variable, layer?.n_runs],
  );
  const listRun = layer && layer.n_runs > 0 ? firstRun.data?.[0]?.run_id : undefined;
  const rasters = useAsync(
    () =>
      hasEntity && (layer!.n_runs === 0 || listRun)
        ? api.spatialRasters({ scenario, variable, run: listRun })
        : Promise.resolve<RasterEntry[]>([]),
    [hasEntity, scenario, variable, listRun],
  );
  const entityNames = useMemo(
    () => [...new Set((rasters.data ?? []).map((r) => r.group_name ?? r.fleet_name).filter((n): n is string => !!n))].sort(),
    [rasters.data],
  );
  useEffect(() => {
    setEntities((prev) => {
      const kept = prev.filter((e) => entityNames.includes(e));
      return kept.length || !entityNames.length ? kept : [entityNames[0]];
    });
  }, [entityNames]);

  const library = useAreaLibrary();
  const chosen = useMemo(() => library.areas.filter((a) => areaIds.includes(a.id)), [library.areas, areaIds]);
  const { problems } = useAreaShapes(scenario || null, chosen);
  const usable = useMemo(() => chosen.filter((a) => !problems[a.id]), [chosen, problems]);

  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const from = Math.max(yearFrom ?? layer?.year_min ?? 0, layer?.year_min ?? 0);
  const to = Math.min(yearTo ?? layer?.year_max ?? 0, layer?.year_max ?? 0);

  return (
    <section className="mapseries">
      <button className="areasummary__toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? "▾" : "▸"} From maps (by area)
      </button>
      <span className="muted mapseries__hint">
        {" "}
        An Ecospace variable summarised within areas, year by year — computed from the maps, not an Ecosim output.
      </span>
      {open && (
        <div className="mapseries__body">
          {layers.loading && <div className="muted">Loading…</div>}
          {!layers.loading && mapScenarios.length === 0 && (
            <div className="muted">None of the plotted scenarios has Ecospace maps.</div>
          )}
          {mapScenarios.length > 0 && (
            <div className="mapseries__controls">
              {mapScenarios.length > 1 && (
                <label className="field">
                  <span>Scenario</span>
                  <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
                    {mapScenarios.map((s) => (
                      <option key={s} value={s}>
                        {scenarioLabel(s)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="field">
                <span>Map variable</span>
                <select value={variable} onChange={(e) => setVariable(e.target.value)}>
                  {variables.map((l) => (
                    <option key={l.variable} value={l.variable}>
                      {l.label ?? l.variable}
                    </option>
                  ))}
                </select>
              </label>
              {hasEntity && (
                <div className="field">
                  <span>{layer!.n_fleets > 0 ? "Fleets" : "Groups"}</span>
                  <div className="mapseries__checks">
                    {entityNames.map((n) => (
                      <label key={n} className="check">
                        <input type="checkbox" checked={entities.includes(n)} onChange={() => setEntities(toggle(entities, n))} />
                        {n}
                      </label>
                    ))}
                  </div>
                </div>
              )}
              <div className="field">
                <span>Areas</span>
                {library.loaded && library.areas.length === 0 ? (
                  <span className="muted">
                    No saved areas yet — draw or pick them in “Spatial data”, step “Area of interest”.
                  </span>
                ) : (
                  <div className="mapseries__checks">
                    {library.areas.map((a) => (
                      <label key={a.id} className="check" title={problems[a.id]}>
                        <input type="checkbox" checked={areaIds.includes(a.id)} onChange={() => setAreaIds(toggle(areaIds, a.id))} />
                        <span className={problems[a.id] ? "aoilist__problem" : undefined}>{a.name}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
          {layer && usable.length > 0 && (!hasEntity || entities.length > 0) && (
            <AreaSummaryPanel
              key={`${scenario}|${variable}`}
              title="Map series"
              scenario={scenario}
              variable={variable}
              variableLabel={layer.label ?? variable}
              entities={hasEntity ? entities : []}
              yearFrom={from}
              yearTo={to}
              run={run || undefined}
              isMonteCarlo={layer.n_runs > 0}
              fixedRun={run || "all"}
              areas={usable}
              note="Aggregated from the Ecospace maps over each area's cells — not an Ecosim result."
            />
          )}
        </div>
      )}
    </section>
  );
}
