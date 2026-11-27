import { useState } from "react";
import { api } from "../../api/client";
import type { RegionLayer, RegionPack } from "../../api/types";
import { useAsync } from "../../api/useAsync";

// Matches the sentinel GET /admin/browse uses for the Windows drive list.
const DRIVES = "__DRIVES__";

function gridLabel(layer: RegionLayer): string {
  return `${layer.grid.ncols}×${layer.grid.nrows} · ${layer.crs}`;
}

/** "ICES subdivisions (8), ICES statistical rectangles (113), 14 management areas" for one grid. */
function layerSummary(layers: RegionLayer[]): string {
  const parts = layers
    .filter((l) => l.kind === "regions")
    .map((l) => `${l.title} (${l.classes.length})`);
  const masks = layers.filter((l) => l.kind === "mask").length;
  if (masks) parts.push(`${masks} management area${masks === 1 ? "" : "s"}`);
  return parts.join(", ");
}

function PackRow({
  pack,
  busy,
  onReimport,
  onRemove,
}: {
  pack: RegionPack;
  busy: boolean;
  onReimport: () => void;
  onRemove: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const grids = new Map<string, RegionLayer[]>();
  for (const layer of pack.layers) {
    const key = gridLabel(layer);
    grids.set(key, [...(grids.get(key) ?? []), layer]);
  }
  return (
    <div className="datasource__loaded-row">
      <div className="datasource__loaded-title">
        <span className="datasource__loaded-name">{pack.name}</span>
        <span className="badge badge--muted datasource__loaded-badge">
          {pack.layers.length} layer{pack.layers.length === 1 ? "" : "s"}
        </span>
      </div>
      <span className="muted mono datasource__loaded-path">{pack.source_path}</span>
      <span className="muted datasource__loaded-meta">
        Loaded: {new Date(pack.imported_at).toLocaleString()}
      </span>
      <ul className="regionpack__grids">
        {[...grids.entries()].map(([grid, layers]) => (
          <li key={grid}>
            <span className="mono">Grid {grid}</span>: {layerSummary(layers)}
          </li>
        ))}
      </ul>
      {pack.warnings.length > 0 && (
        <details className="regionpack__notes">
          <summary className="muted">
            {pack.warnings.length} file{pack.warnings.length === 1 ? "" : "s"} not used
          </summary>
          <ul className="regionpack__notes-list">
            {pack.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
      )}
      <div className="datasource__loaded-actions-row">
        {confirming ? (
          <span className="datasource__loaded-confirm">
            <span className="muted">Remove these areas? Saved areas that use them stop working until loaded again.</span>
            <button className="btn btn--danger" onClick={onRemove} disabled={busy}>
              {busy ? "Removing…" : "Yes, remove"}
            </button>
            <button className="btn btn--ghost" onClick={() => setConfirming(false)} disabled={busy}>
              Cancel
            </button>
          </span>
        ) : (
          <span className="datasource__loaded-actions">
            <span className="datasource__loaded-actions-group">
              <button
                className="btn btn--ghost"
                onClick={onReimport}
                disabled={busy}
                title="Read the same folder or .zip again (e.g. after its maps were updated)"
              >
                {busy ? "Loading…" : "Load again"}
              </button>
              <button className="btn btn--danger" onClick={() => setConfirming(true)} disabled={busy}>
                Remove
              </button>
            </span>
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * Reference areas (optional data): region map packs -- ICES subdivisions and
 * rectangles, management areas -- prepared on a model's grid. A pack is
 * copied into the user's profile on load (backend regions/store.py); analyses
 * then offer the layers that fit the model's grid.
 */
export function ReferenceAreasPanel({ onChanged }: { onChanged: () => void }) {
  const [token, setToken] = useState(0);
  const packs = useAsync(() => api.regionPacks(), [token]);
  const [tab, setTab] = useState<"loaded" | "browse" | null>(null);
  const shownTab = tab ?? (packs.data && packs.data.length > 0 ? "loaded" : "browse");

  const [browsePath, setBrowsePath] = useState<string | undefined>(undefined);
  const browse = useAsync(() => api.browse(browsePath, { zip: true }), [browsePath]);
  const [jumpInput, setJumpInput] = useState("");
  const [nameInput, setNameInput] = useState("");
  const [busy, setBusy] = useState<string | null>(null); // pack id, or the path being loaded
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    setToken((t) => t + 1);
    onChanged();
  };

  const load = async (path: string, name?: string) => {
    setBusy(path);
    setError(null);
    try {
      await api.importRegionPack(path, name);
      setNameInput("");
      setTab("loaded");
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (pack: RegionPack) => {
    setBusy(pack.id);
    setError(null);
    try {
      await api.removeRegionPack(pack.id);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const working = busy !== null;

  return (
    <div className="datasource">
      <div className="datasource__intro">
        <h1 className="datasource__title">Reference areas</h1>
        <p className="datasource__subtitle">
          Region maps prepared on your model's grid: ICES subdivisions and statistical rectangles, and management
          areas such as EEZs, Natura 2000 or fishing closures. Analyses can then use any combination of them, or an
          area you draw yourself.
        </p>
        <p className="datasource__hint">
          Choose a folder or a .zip with ESRI ASCII maps (.asc with its .prj): region maps with a .csv legend, or 0/1
          masks. A copy is kept with your data, so the original can be moved later. Only maps on the same grid as
          your model are offered in analyses.
        </p>
      </div>

      {error && <div className="error datasource__error">{error}</div>}

      <div className="datasource__tabs">
        <button
          className={`datasource__tab${shownTab === "loaded" ? " is-active" : ""}`}
          onClick={() => setTab("loaded")}
        >
          Loaded{packs.data && packs.data.length > 0 ? ` (${packs.data.length})` : ""}
        </button>
        <button
          className={`datasource__tab${shownTab === "browse" ? " is-active" : ""}`}
          onClick={() => setTab("browse")}
        >
          Browse for a folder or .zip
        </button>
      </div>

      {shownTab === "loaded" && (
        <section className="datasource__loaded">
          {packs.loading && !packs.data && <p className="muted datasource__loaded-empty">Loading…</p>}
          {packs.error && <div className="error pad">{packs.error}</div>}
          {packs.data?.length === 0 && (
            <p className="muted datasource__loaded-empty">
              No reference areas loaded yet — switch to “Browse for a folder or .zip” to add some.
            </p>
          )}
          {packs.data?.map((pack) => (
            <PackRow
              key={pack.id}
              pack={pack}
              busy={busy === pack.id || busy === pack.source_path}
              onReimport={() => void load(pack.source_path, pack.name)}
              onRemove={() => void remove(pack)}
            />
          ))}
        </section>
      )}

      {shownTab === "browse" && (
        <section className="datasource__section">
          <div className="datasource__pathrow">
            <input
              className="datasource__pathinput mono"
              placeholder="Jump to a path (a folder or a .zip)…"
              value={jumpInput}
              onChange={(e) => setJumpInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && jumpInput.trim()) {
                  const p = jumpInput.trim();
                  if (p.toLowerCase().endsWith(".zip")) void load(p, nameInput.trim());
                  else setBrowsePath(p);
                }
              }}
              disabled={working}
            />
          </div>
          <div className="datasource__browser">
            {browse.loading && <div className="muted pad">Loading…</div>}
            {browse.error && <div className="error pad">{browse.error}</div>}
            {browse.data && (
              <>
                <div className="datasource__breadcrumb mono">
                  {!browse.data.is_drives_list && (
                    <button className="badge badge--btn" onClick={() => setBrowsePath(DRIVES)} disabled={working}>
                      💻 This PC
                    </button>
                  )}
                  {browse.data.parent !== null && (
                    <button
                      className="badge badge--btn"
                      onClick={() => setBrowsePath(browse.data!.parent!)}
                      disabled={working}
                    >
                      .. up
                    </button>
                  )}
                  <span>{browse.data.path}</span>
                </div>
                <ul className="datasource__folderlist">
                  {browse.data.entries.length === 0 && (
                    <li className="muted datasource__folderempty">
                      {browse.data.is_drives_list ? "No drives found." : "No subfolders or .zip files here."}
                    </li>
                  )}
                  {browse.data.entries.map((entry) =>
                    entry.is_file ? (
                      <li key={entry.path} className="datasource__folderitem">
                        <button
                          className="datasource__folderbtn"
                          onClick={() => void load(entry.path, nameInput.trim())}
                          title="Load the maps in this .zip"
                          disabled={working}
                        >
                          📦 {entry.name}
                          <span className="badge badge--muted datasource__hint-badge">
                            {busy === entry.path ? "Loading…" : "click to load"}
                          </span>
                        </button>
                      </li>
                    ) : (
                      <li key={entry.path} className="datasource__folderitem">
                        <button
                          className="datasource__folderbtn"
                          onClick={() => setBrowsePath(entry.path)}
                          title="Open"
                          disabled={working}
                        >
                          {browse.data!.is_drives_list ? "💽" : "📁"} {entry.name}
                        </button>
                      </li>
                    ),
                  )}
                </ul>
                {!browse.data.is_drives_list && (
                  <div className="datasource__confirmbar">
                    <input
                      className="datasource__nameinput"
                      placeholder="Name (optional)"
                      value={nameInput}
                      onChange={(e) => setNameInput(e.target.value)}
                      disabled={working}
                    />
                    <button
                      className="btn"
                      onClick={() => void load(browse.data!.path, nameInput.trim())}
                      disabled={working}
                    >
                      {busy === browse.data.path ? "Reading maps…" : "Use this folder"}
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
