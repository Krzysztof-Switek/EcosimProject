import { useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { DataSourceKind } from "../../api/types";

// Matches the sentinel the backend's GET /admin/browse checks for (see
// api/routers/sources.py `_DRIVES`) -- passed through opaquely, the
// frontend never needs to know it's not a real path.
const DRIVES = "__DRIVES__";

const COPY: Record<DataSourceKind, { title: string; blurb: string; hint: string }> = {
  output: {
    title: "Model output data",
    blurb: "Ecosim/Ecospace simulation results — biomass, catch, effort, spatial maps.",
    hint:
      "Select any folder that contains your model's results somewhere inside it — " +
      "results are found by scanning recursively, so it doesn't matter how deep they " +
      "are or what the containing folders are named. Any real output is accepted, " +
      "including Monte Carlo/multi-run results. A group/fleet dictionary " +
      "(Mapa_grupy_fleets.xlsx) is entirely optional and only used to resolve names " +
      "if one happens to be nearby.",
  },
  input: {
    title: "Model input data",
    blurb: "Driver / forcing grids used to run the model — optional.",
    hint:
      "Select any folder that contains your driver data somewhere inside it — " +
      "found by scanning recursively, regardless of folder names or depth. " +
      "Optional: only needed for driver-grid variables.",
  },
};

/**
 * Kind-scoped picker for one of the two independent data sources (see
 * docs/data-contract.md's "Oczekiwany układ katalogów źródłowych"): model
 * OUTPUT (mandatory -- models/scenarios/groups all derive from it) and model
 * INPUT (optional, driver grids only). Reached from the two upload tiles on
 * Landing; lets the user point the app at a folder -- a local path today, a
 * subfolder of a shared network drive once this runs on a server -- instead
 * of a fixed env var baked in at process start.
 *
 * Deliberately just "point at a folder and go" -- no list of remembered past
 * sources to pick from (adding a new one always replaces whatever was set
 * before, see WorkspaceRegistry.add_source). A per-user history would make
 * sense once there's per-user accounts; for a single shared instance today
 * it's just clutter. See docs/Plans and TO_DO lists/27.08_data_upload_PLAN.md.
 */
export function DataSourcePanel({ kind, onActivated }: { kind: DataSourceKind; onActivated: () => void }) {
  const copy = COPY[kind];

  const [browsePath, setBrowsePath] = useState<string | undefined>(undefined);
  const browse = useAsync(() => api.browse(browsePath), [browsePath]);

  const [pathInput, setPathInput] = useState("");
  const [nameInput, setNameInput] = useState("");
  const [adding, setAdding] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  // Set only when activation succeeded but no group/fleet dictionary was
  // found -- non-blocking (the data is real and already ingested), just
  // needs a beat of visibility before handing off to onActivated(), since
  // the panel normally closes immediately on success.
  const [noDictNotice, setNoDictNotice] = useState(false);

  const chooseFolder = (path: string, suggestedName: string) => {
    setPathInput(path);
    setNameInput(suggestedName);
  };

  const addAndActivate = async () => {
    if (!pathInput.trim()) return;
    setAdding(true);
    setActionError(null);
    try {
      const name = nameInput.trim() || pathInput.trim().split(/[\\/]/).filter(Boolean).pop() || pathInput;
      const source = await api.addSource(name, pathInput.trim(), kind);
      const result = await api.activateSource(source.id);
      setPathInput("");
      setNameInput("");
      if (kind === "output" && !result.group_dictionary_found) {
        setNoDictNotice(true);
      } else {
        onActivated();
      }
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="datasource">
      <div className="datasource__intro">
        <h1 className="datasource__title">{copy.title}</h1>
        <p className="datasource__subtitle">{copy.blurb}</p>
        <p className="datasource__hint">{copy.hint}</p>
      </div>

      {actionError && <div className="error datasource__error">{actionError}</div>}

      {noDictNotice && (
        <div className="datasource__notice datasource__section">
          <p>
            <strong>Data loaded.</strong> No group/fleet dictionary
            (Mapa_grupy_fleets.xlsx) was found nearby, so group/fleet <em>names</em> couldn't
            be resolved for time-series data — you'll see numeric ids instead. Spatial map
            names are unaffected (they're read from filenames directly). Add a dictionary
            later and rescan to fill in the names.
          </p>
          <button className="btn" onClick={onActivated}>
            Continue
          </button>
        </div>
      )}

      {!noDictNotice && <section className="datasource__section">
        <div className="datasource__pathrow">
          <input
            className="datasource__pathinput mono"
            placeholder="Paste a path, or browse below…"
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
          />
          <input
            className="datasource__nameinput"
            placeholder="Name (e.g. Baltic Sea 2026-08)"
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
          />
          <button className="btn" onClick={addAndActivate} disabled={adding || !pathInput.trim()}>
            {adding ? "Scanning…" : "Use this data"}
          </button>
        </div>

        <div className="datasource__browser">
          {browse.loading && <div className="muted pad">Loading…</div>}
          {browse.error && <div className="error pad">{browse.error}</div>}
          {browse.data && (
            <>
              <div className="datasource__breadcrumb mono">
                {!browse.data.is_drives_list && (
                  <button className="badge badge--btn" onClick={() => setBrowsePath(DRIVES)}>
                    💻 This PC
                  </button>
                )}
                {browse.data.parent !== null && (
                  <button className="badge badge--btn" onClick={() => setBrowsePath(browse.data!.parent!)}>
                    .. up
                  </button>
                )}
                <span>{browse.data.path}</span>
                {!browse.data.is_drives_list && (
                  <button
                    className="btn btn--ghost datasource__usehere"
                    onClick={() => chooseFolder(browse.data!.path, browse.data!.path.split(/[\\/]/).filter(Boolean).pop() ?? browse.data!.path)}
                  >
                    Use this folder
                  </button>
                )}
              </div>
              <ul className="datasource__folderlist">
                {browse.data.entries.length === 0 && (
                  <li className="muted datasource__folderempty">
                    {browse.data.is_drives_list ? "No drives found." : "No subfolders here."}
                  </li>
                )}
                {browse.data.entries.map((entry) => (
                  <li key={entry.path} className="datasource__folderitem">
                    <button
                      className="datasource__folderbtn"
                      onClick={() => setBrowsePath(entry.path)}
                      title="Open"
                    >
                      {browse.data!.is_drives_list ? "💽" : "📁"} {entry.name}
                      {entry.looks_like_source && (
                        <span className="badge badge--muted datasource__hint-badge">looks like a model export</span>
                      )}
                    </button>
                    {!browse.data!.is_drives_list && (
                      <button className="btn btn--ghost" onClick={() => chooseFolder(entry.path, entry.name)}>
                        Use
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </section>}
    </div>
  );
}
