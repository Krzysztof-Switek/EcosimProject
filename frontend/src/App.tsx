import { useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import { useAsync } from "./api/useAsync";
import { buildVariableIndex } from "./features/catalog/catalogIndex";
import { CatalogPanel } from "./features/catalog/CatalogPanel";
import { AnalysisView } from "./features/timeseries/AnalysisView";

export default function App() {
  // Theme (persisted); applied as data-theme on <html> for the CSS variables.
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("theme") as "light" | "dark") || "light",
  );
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  // Bumping this token re-runs every catalog fetch (used after a data reload).
  const [reloadToken, setReloadToken] = useState(0);
  const [reloading, setReloading] = useState(false);
  const [reloadMsg, setReloadMsg] = useState<string | null>(null);

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

  // Map scenario id -> authoritative EcosimScenario label for display.
  const scenarioLabels = useMemo(() => {
    const m: Record<string, string> = {};
    for (const s of scenarios.data ?? []) m[s.scenario] = s.label ?? s.scenario;
    return m;
  }, [scenarios.data]);

  const [freq, setFreq] = useState<"annual" | "monthly">("annual");
  // Multi-select: variables are tracked freq-agnostically by `${domain}|${variable}`
  // so a selection survives switching Annual/Monthly.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const toggleVar = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const removeVar = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  const clearVars = () => setSelectedIds(new Set());

  // Level-0 split: only variables of the active frequency are navigable.
  const inFreq = useMemo(() => variables.filter((v) => v.freq === freq), [variables, freq]);
  const selectedVariables = useMemo(
    () => inFreq.filter((v) => selectedIds.has(`${v.domain}|${v.variable}`)),
    [inFreq, selectedIds],
  );

  const loading = tree.loading || groups.loading || fleets.loading;
  const error = tree.error || groups.error || fleets.error;

  return (
    <div className="app">
      <header className="app__bar">
        <span className="app__brand">Ecosim · Results Explorer</span>
        <div className="app__bar-right">
          {reloadMsg && <span className="muted">{reloadMsg}</span>}
          <span className="muted">{variables.length} variables</span>
          <button
            className="btn btn--ghost"
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            title="Toggle dark mode"
          >
            {theme === "dark" ? "☀ Light" : "🌙 Dark"}
          </button>
          <button className="btn" onClick={reloadData} disabled={reloading}>
            {reloading ? "Reloading…" : "Reload Data"}
          </button>
        </div>
      </header>

      {error && <div className="error pad">Cannot reach API: {error}</div>}
      {loading && <div className="muted pad">Loading catalog…</div>}

      {!loading && !error && (
        <div className="app__body">
          <CatalogPanel
            variables={inFreq}
            freq={freq}
            onFreqChange={setFreq}
            selectedIds={selectedIds}
            onToggle={toggleVar}
          />
          <main className="app__main">
            {selectedVariables.length > 0 ? (
              <AnalysisView
                key={freq}
                variables={selectedVariables}
                freq={freq}
                scenarioLabels={scenarioLabels}
                groups={groups.data ?? []}
                fleets={fleets.data ?? []}
                onRemove={removeVar}
                onClear={clearVars}
              />
            ) : (
              <div className="muted pad">
                Select one or more variables from the catalog (check the boxes) to build an analysis.
              </div>
            )}
          </main>
        </div>
      )}
    </div>
  );
}
