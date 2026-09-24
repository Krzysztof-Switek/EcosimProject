import { useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import { useAsync } from "./api/useAsync";
import type { DimItem } from "./api/types";
import { buildVariableIndex, type VariableKey } from "./features/catalog/catalogIndex";
import { Sidebar } from "./features/catalog/Sidebar";
import { AnalysisView } from "./features/timeseries/AnalysisView";
import { Landing } from "./features/home/Landing";
import { SpatialView } from "./features/spatial/SpatialView";
import { MonteCarloView } from "./features/montecarlo/MonteCarloView";
import { DataSourcePanel } from "./features/datasource/DataSourcePanel";
import { useActivationTracker, activationLabel } from "./features/datasource/useActivationTracker";

const varId = (v: { domain: string; variable: string }) => `${v.domain}|${v.variable}`;

type Module = "spatial" | "timeseries" | "montecarlo";

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

  // Which folders the app reads EwE model output/input data from -- see
  // features/datasource/DataSourcePanel.tsx. Output is mandatory (models/
  // scenarios/groups all derive from it) and gates the "Explore" tiles on
  // Landing; input is optional. Neither blocks the whole app the way a
  // single combined source used to -- Landing's row 1 is always reachable
  // so a fresh install can point at data without anything else pretending
  // to work first.
  const [sourceToken, setSourceToken] = useState(0);
  const [sourcePanelKind, setSourcePanelKind] = useState<"output" | "input" | null>(null);
  const sources = useAsync(() => api.sources(), [sourceToken]);
  const activeOutput = sources.data?.find((s) => s.kind === "output" && s.active) ?? null;
  const activeInput = sources.data?.find((s) => s.kind === "input" && s.active) ?? null;

  // Bumping this token re-runs every catalog fetch (used after a data reload).
  const [reloadToken, setReloadToken] = useState(0);
  const [reloading, setReloading] = useState(false);
  const [reloadMsg, setReloadMsg] = useState<string | null>(null);

  // Ingestion for a large dataset can take a long time -- this tracks it
  // independently of which screen is open (survives navigating away, even a
  // page reload) instead of dying with whichever component started it. See
  // useActivationTracker's own docstring for why this moved up from
  // DataSourcePanel.
  const activation = useActivationTracker(() => {
    setSourceToken((t) => t + 1);
    setReloadToken((t) => t + 1);
  });

  const dataSourceReadout = (
    <span className="muted app__sourcereadout">
      📤 {activeOutput?.name ?? "—"}
      {activeInput && ` · 📥 ${activeInput.name}`}
    </span>
  );

  // Visible from every screen, not just Landing, so a large dataset loading
  // in the background never requires sitting on one specific page to see
  // whether it's still working.
  const activationPill = activation.activating && (
    <span className="badge badge--muted app__activation-pill" title={activation.activating.name}>
      ⏳ {activationLabel(activation.status)}
    </span>
  );

  const models = useAsync(() => api.models(), [reloadToken]);
  const tree = useAsync(() => api.tree(), [reloadToken]);
  const scenarios = useAsync(() => api.scenarios(), [reloadToken]);
  // No group/fleet name dictionary exists any more (removed 2026-08-28, see
  // docs/Plans and TO_DO lists/28.08_session_summary.md) -- these stay as
  // empty arrays so SpatialView/AnalysisView's existing "no dictionary"
  // fallback (alphabetical sort, no name-filter options) is simply the only
  // state now, not a conditional one.
  const groups: DimItem[] = [];
  const fleets: DimItem[] = [];

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

  // Effective (plotted) series: the full pool chosen in steps 1–2 by default --
  // picking a variable should show what you already selected upstream, not
  // demand a third, seemingly-duplicate confirmation. The per-variable picker
  // (docked "Models & scenarios" panel) is an *override* for the rarer case of
  // wanting a different subset for one specific variable; an override is kept
  // only for currently-available ids (dropped if steps 1–2 later narrow the pool).
  const effectiveScenarios = (v: VariableKey): string[] => {
    const avail = availableScenarios(v);
    const override = perVarScenarios[varId(v)];
    return override ? override.filter((s) => avail.includes(s)) : avail;
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

  const loading = tree.loading || models.loading;
  const error = tree.error || models.error;

  const homeBtn = (
    <button className="btn btn--ghost" onClick={() => setModule(null)} title="Back to start">
      ← Home
    </button>
  );

  if (sources.loading) {
    return (
      <div className="app">
        <header className="app__bar">
          <span className="app__brand">Ecosim · Results Explorer</span>
          <div className="app__bar-right">{themeToggle}</div>
        </header>
        <div className="muted pad">Loading…</div>
      </div>
    );
  }

  if (sources.error) {
    return (
      <div className="app">
        <header className="app__bar">
          <span className="app__brand">Ecosim · Results Explorer</span>
          <div className="app__bar-right">{themeToggle}</div>
        </header>
        <div className="error pad">Cannot reach API: {sources.error}</div>
      </div>
    );
  }

  if (sourcePanelKind !== null) {
    return (
      <div className="app">
        <header className="app__bar">
          <div className="app__bar-left">
            <button className="btn btn--ghost" onClick={() => setSourcePanelKind(null)} title="Back">
              ← Back
            </button>
            <span className="app__brand">Ecosim · Results Explorer</span>
          </div>
          <div className="app__bar-right">{themeToggle}</div>
        </header>
        <DataSourcePanel
          kind={sourcePanelKind}
          sources={(sources.data ?? []).filter((s) => s.kind === sourcePanelKind)}
          onActivationStarted={(source) => {
            // Registration succeeded and ingestion has been kicked off in
            // the background -- leave immediately rather than making the
            // user sit on this screen watching it finish. Progress keeps
            // showing on the Landing tile / app bar from here.
            activation.start(source);
            setSourcePanelKind(null);
          }}
          onSourceRemoved={() => {
            // Same refresh as a finished activation (see useActivationTracker
            // above) -- unloading a source changes what the catalog/tiles
            // should show just as much as loading one does.
            setSourceToken((t) => t + 1);
            setReloadToken((t) => t + 1);
          }}
          activation={activation}
        />
      </div>
    );
  }

  // No active output source yet, or the user hasn't picked a module: both
  // land on Landing, whose row 1 (data) is always reachable and row 2
  // (explore) is disabled until output is set -- see Landing.tsx.
  if (module === null || activeOutput === null) {
    return (
      <div className="app">
        <header className="app__bar">
          <span className="app__brand">Ecosim · Results Explorer</span>
          <div className="app__bar-right">{themeToggle}</div>
        </header>
        {activation.error && (
          <div className="error pad app__activation-error">
            {activation.error}
            <button className="btn btn--ghost" onClick={activation.dismissError}>✕</button>
          </div>
        )}
        <Landing
          onSelect={setModule}
          onOpenSource={setSourcePanelKind}
          activeOutput={activeOutput}
          outputCount={(sources.data ?? []).filter((s) => s.kind === "output").length}
          inputCount={(sources.data ?? []).filter((s) => s.kind === "input").length}
          activating={activation.activating}
          activatingStatus={activation.status}
        />
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
          <div className="app__bar-right">
            {activationPill}
            {dataSourceReadout}
            {themeToggle}
          </div>
        </header>
        <div className="app__body">
          <main className="app__main">
            <SpatialView groups={groups} fleets={fleets} />
          </main>
        </div>
      </div>
    );
  }

  if (module === "montecarlo") {
    return (
      <div className="app">
        <header className="app__bar">
          <div className="app__bar-left">
            {homeBtn}
            <span className="app__brand">Monte Carlo</span>
          </div>
          <div className="app__bar-right">
            {activationPill}
            {dataSourceReadout}
            {themeToggle}
          </div>
        </header>
        <div className="app__body">
          <main className="app__main">
            <MonteCarloView activeOutput={activeOutput} />
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
          {activationPill}
          {dataSourceReadout}
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
                groups={groups}
                fleets={fleets}
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
