import { useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import { useAsync } from "./api/useAsync";
import { buildVariableIndex, type VariableKey } from "./features/catalog/catalogIndex";
import { Sidebar } from "./features/catalog/Sidebar";
import { AnalysisView } from "./features/timeseries/AnalysisView";
import { Landing } from "./features/home/Landing";
import { SpatialView } from "./features/spatial/SpatialView";

const varId = (v: { domain: string; variable: string }) => `${v.domain}|${v.variable}`;

type Module = "spatial" | "timeseries";

export default function App() {
  // Top-level choice made on the landing screen: which module the user is in.
  const [module, setModule] = useState<Module | null>(null);

  // Theme (persisted); applied as data-theme on <html> for the CSS variables.
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("theme") as "light" | "dark") || "light",
  );
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);
  const themeToggle = (
    <button
      className="btn btn--ghost"
      onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
      title="Toggle dark mode"
    >
      {theme === "dark" ? "☀ Light" : "🌙 Dark"}
    </button>
  );

  // Bumping this token re-runs every catalog fetch (used after a data reload).
  const [reloadToken, setReloadToken] = useState(0);
  const [reloading, setReloading] = useState(false);
  const [reloadMsg, setReloadMsg] = useState<string | null>(null);

  const models = useAsync(() => api.models(), [reloadToken]);
  const tree = useAsync(() => api.tree(), [reloadToken]);
  const groups = useAsync(() => api.groups(), [reloadToken]);
  const fleets = useAsync(() => api.fleets(), [reloadToken]);
  const scenarios = useAsync(() => api.scenarios(), [reloadToken]);

  const reloadData = async () => {
    setReloading(true);
    setReloadMsg(null);
    try {
      const r = await api.reload();
      setReloadMsg(
        `Loaded ${r.datasets} datasets from ${r.files_read} files` +
          (r.errors ? ` (${r.errors} skipped)` : ""),
      );
      setReloadToken((t) => t + 1);
    } catch (e) {
      setReloadMsg(`Reload failed: ${(e as Error).message}`);
    } finally {
      setReloading(false);
    }
  };

  const variables = useMemo(
    () => (tree.data ? buildVariableIndex(tree.data) : []),
    [tree.data],
  );

  // scenario id -> authoritative EcosimScenario label for display.
  const scenarioLabels = useMemo(() => {
    const m: Record<string, string> = {};
    for (const s of scenarios.data ?? []) m[s.scenario] = s.label ?? s.scenario;
    return m;
  }, [scenarios.data]);
  const scenarioLabel = (s: string) => scenarioLabels[s] ?? s;

  // ── Navigation state ──────────────────────────────────────────────────────
  const [freq, setFreq] = useState<"annual" | "monthly">("annual");
  // Step 1–2: the global pool of models and (output) scenarios.
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const [selectedScenarios, setSelectedScenarios] = useState<Set<string>>(new Set());
  // Step 4: chosen variables, tracked freq-agnostically by `${domain}|${variable}`.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  // The variable whose model/scenario picker is shown in the controls column.
  const [focusedVarId, setFocusedVarId] = useState<string | null>(null);
  // Per-variable scenario overrides (absent ⇒ follow the pool default).
  const [perVarScenarios, setPerVarScenarios] = useState<Record<string, string[]>>({});

  // Start empty (and reset on each reload): nothing is preselected — the user
  // builds the selection step by step (models → scenarios → variables).
  useEffect(() => {
    if (!models.data) return;
    setSelectedModels(new Set());
    setSelectedScenarios(new Set());
    setSelectedIds(new Set());
    setFocusedVarId(null);
    setPerVarScenarios({});
  }, [models.data]);

  const scenariosOfModel = (model: string): string[] =>
    models.data?.find((m) => m.model === model)?.scenarios.map((s) => s.scenario) ?? [];

  const toggleModel = (model: string) => {
    const ids = scenariosOfModel(model);
    setSelectedModels((prev) => {
      const next = new Set(prev);
      const turningOff = next.has(model);
      turningOff ? next.delete(model) : next.add(model);
      // Enabling a model only makes its scenarios available in step 2 (nothing is
      // preselected); disabling it drops any of its scenarios already chosen.
      if (turningOff) {
        setSelectedScenarios((scns) => {
          const s = new Set(scns);
          for (const id of ids) s.delete(id);
          return s;
        });
      }
      return next;
    });
  };

  const toggleScenario = (scenario: string) =>
    setSelectedScenarios((prev) => {
      const next = new Set(prev);
      next.has(scenario) ? next.delete(scenario) : next.add(scenario);
      return next;
    });

  const setModelScenarios = (ids: string[], on: boolean) =>
    setSelectedScenarios((prev) => {
      const next = new Set(prev);
      for (const id of ids) (on ? next.add(id) : next.delete(id));
      return next;
    });

  const toggleVar = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        setFocusedVarId((f) => (f === id ? null : f));
      } else {
        next.add(id);
        setFocusedVarId(id); // focus newly added variable
      }
      return next;
    });
  // Click a variable name/badge: ensure it is selected and focus its picker.
  const focusVar = (id: string) => {
    setSelectedIds((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
    setFocusedVarId(id);
  };
  const removeVar = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
    setFocusedVarId((f) => (f === id ? null : f));
  };
  const clearVars = () => {
    setSelectedIds(new Set());
    setFocusedVarId(null);
  };

  const setVarScenarios = (id: string, scns: string[] | null) =>
    setPerVarScenarios((prev) => {
      const next = { ...prev };
      if (scns === null) delete next[id];
      else next[id] = scns;
      return next;
    });

  // Scenarios a variable may plot, gated by the earlier steps: an output
  // (model, scenario) is available only if BOTH its model (step 1) and scenario
  // (step 2) were chosen; input drivers have no model step, so they are always
  // available. This is the candidate set shown in the step-5 picker.
  const availableScenarios = (v: VariableKey): string[] =>
    v.combos
      .filter((c) =>
        c.model === null ? true : selectedModels.has(c.model) && selectedScenarios.has(c.scenario),
      )
      .map((c) => c.scenario);

  // Effective (plotted) series: nothing by default — the user explicitly picks
  // in the step-5 picker. An override is kept only for currently-available ids.
  const effectiveScenarios = (v: VariableKey): string[] => {
    const avail = new Set(availableScenarios(v));
    const override = perVarScenarios[varId(v)];
    return override ? override.filter((s) => avail.has(s)) : [];
  };

  // Level-0 split: only variables of the active frequency are navigable.
  const inFreq = useMemo(() => variables.filter((v) => v.freq === freq), [variables, freq]);
  const selectedVariables = useMemo(
    () => inFreq.filter((v) => selectedIds.has(varId(v))),
    [inFreq, selectedIds],
  );
  // The focused variable drives the docked model/scenario picker; fall back to
  // the first selected one so the picker is always visible when there's data.
  const focusedVariable = useMemo(() => {
    if (selectedVariables.length === 0) return null;
    return selectedVariables.find((v) => varId(v) === focusedVarId) ?? selectedVariables[0];
  }, [selectedVariables, focusedVarId]);

  const loading = tree.loading || models.loading || groups.loading || fleets.loading;
  const error = tree.error || models.error || groups.error || fleets.error;

  const homeBtn = (
    <button className="btn btn--ghost" onClick={() => setModule(null)} title="Back to start">
      ← Home
    </button>
  );

  if (module === null) {
    return (
      <div className="app">
        <header className="app__bar">
          <span className="app__brand">Ecosim · Results Explorer</span>
          <div className="app__bar-right">{themeToggle}</div>
        </header>
        <Landing onSelect={setModule} />
      </div>
    );
  }

  if (module === "spatial") {
    return (
      <div className="app">
        <header className="app__bar">
          <div className="app__bar-left">
            {homeBtn}
            <span className="app__brand">Spatial data</span>
          </div>
          <div className="app__bar-right">{themeToggle}</div>
        </header>
        <div className="app__body">
          <main className="app__main">
            <SpatialView groups={groups.data ?? []} fleets={fleets.data ?? []} />
          </main>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app__bar">
        <div className="app__bar-left">
          {homeBtn}
          <span className="app__brand">Ecosim · Results Explorer</span>
        </div>
        <div className="app__bar-right">
          {reloadMsg && <span className="muted">{reloadMsg}</span>}
          <span className="muted">
            {models.data?.length ?? 0} models · {variables.length} variables
          </span>
          {themeToggle}
          <button className="btn" onClick={reloadData} disabled={reloading}>
            {reloading ? "Reloading…" : "Reload Data"}
          </button>
        </div>
      </header>

      {error && <div className="error pad">Cannot reach API: {error}</div>}
      {loading && <div className="muted pad">Loading catalog…</div>}

      {!loading && !error && (
        <div className="app__body">
          <Sidebar
            models={models.data ?? []}
            variables={inFreq}
            freq={freq}
            onFreqChange={setFreq}
            selectedModels={selectedModels}
            onToggleModel={toggleModel}
            selectedScenarios={selectedScenarios}
            onToggleScenario={toggleScenario}
            onSetModelScenarios={setModelScenarios}
            selectedVarIds={selectedIds}
            onToggleVar={toggleVar}
            focusedVarId={focusedVariable ? varId(focusedVariable) : null}
            onFocusVar={focusVar}
            effectiveScenarios={effectiveScenarios}
          />
          <main className="app__main">
            {selectedVariables.length > 0 ? (
              <AnalysisView
                key={freq}
                variables={selectedVariables}
                freq={freq}
                scenarioLabel={scenarioLabel}
                scenariosForVar={effectiveScenarios}
                availableScenarios={availableScenarios}
                groups={groups.data ?? []}
                fleets={fleets.data ?? []}
                onRemove={removeVar}
                onClear={clearVars}
                focusedVariable={focusedVariable}
                hasOverride={(id) => id in perVarScenarios}
                onSetVarScenarios={setVarScenarios}
                onFocusVar={focusVar}
              />
            ) : (
              <div className="muted pad">
                Pick models and scenarios (steps 1–2), then check one or more variables
                (step 4) to build an analysis.
              </div>
            )}
          </main>
        </div>
      )}
    </div>
  );
}
