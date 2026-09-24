import { useState } from "react";
import { api, asNotLocal } from "../../api/client";
import type { ActivationStatus, NotLocalInfo } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { DataSource, DataSourceKind } from "../../api/types";
import { activationLabel, type ActivatingSource } from "./useActivationTracker";

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
      "including Monte Carlo/multi-run results.",
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

// Same icon language as the Landing tiles (features/home/Landing.tsx) --
// what a source's data turned out to actually contain, shown as a small
// badge in "Indexed data" so it's visible without opening an Explore tile.
const DATA_KIND_META: Record<string, { icon: string; label: string; className: string }> = {
  spatial: { icon: "🗺️", label: "Spatial", className: "badge--kind-spatial" },
  timeseries: { icon: "📈", label: "Time series", className: "badge--kind-timeseries" },
  montecarlo: { icon: "🎲", label: "Monte Carlo", className: "badge--kind-montecarlo" },
  mixed: { icon: "🗺️📈", label: "Spatial + Time series", className: "badge--kind-mixed" },
};

/** "3906" -> "~1 hr 5 min"; "40" -> "under a minute". Deliberately just the
 * last observed duration, never recomputed from a fresh file count -- see
 * DataSourcePanel's docstring for why. */
function formatDuration(seconds: number): string {
  if (seconds < 60) return "under a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `~${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  return rem ? `~${hours} hr ${rem} min` : `~${hours} hr`;
}

/** "402000000" -> "402 MB"; "0" -> "0 B". Disk space a source's own cache
 * slot uses (see api/types.ts's cache_size_bytes docstring). */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 100 ? Math.round(value) : Math.round(value * 10) / 10} ${units[unit]}`;
}

/**
 * Kind-scoped picker for one of the two independent data sources (see
 * docs/data-contract.md's "Oczekiwany układ katalogów źródłowych"): model
 * OUTPUT (mandatory -- models/scenarios/groups all derive from it) and model
 * INPUT (optional, driver grids only). Reached from the two upload tiles on
 * Landing; lets the user point the app at a folder -- a local path today, a
 * subfolder of a shared network drive once this runs on a server -- instead
 * of a fixed env var baked in at process start.
 *
 * "Indexed data" section (reworked 2026-08-28, was "Currently loaded"):
 * every source of this kind ever added is now shown, not just the active
 * one -- each gets its own independently-cached ingest output on the
 * backend (see core/config.py's per-source-cache docstring), so switching
 * back to a previously-scanned source ("Use this") is instant instead of a
 * full rescan. Cache invalidation is 100% manual and per-source, by
 * explicit user request: the app never decides on its own that a source's
 * raw data changed -- "Rescan" always targets exactly the one row clicked,
 * never "everything". "Remove" now also deletes that source's on-disk
 * cache, not just its registry entry.
 *
 * This panel's job ends the moment an activate/rescan has been *started* --
 * it does not wait around for it to finish (that used to make this the one
 * screen you had to sit on for however long a large dataset took; the
 * running operation is tracked by App.tsx's useActivationTracker instead,
 * visible from the Landing tile and the app bar, so leaving this screen the
 * instant it's accepted is exactly the right thing to do, not something
 * that risks losing progress). See onActivationStarted below.
 *
 * Two browser-style tabs (added 2026-08-28, user request once "Indexed
 * data" could hold more than one row): "Indexed data" and "Browse for a
 * folder" no longer compete for vertical space stacked on top of each
 * other -- defaults to whichever is actually useful right now (Indexed
 * data if anything's already there to manage, Browse otherwise).
 */
export function DataSourcePanel({
  kind,
  sources,
  onActivationStarted,
  onSourceRemoved,
  activation,
}: {
  kind: DataSourceKind;
  sources: DataSource[];
  onActivationStarted: (source: ActivatingSource) => void;
  onSourceRemoved: () => void;
  activation: {
    activating: ActivatingSource | null;
    status: ActivationStatus | null;
    cancel: () => void;
  };
}) {
  const copy = COPY[kind];

  // All hooks live above any early return (see the blocking-view branch
  // below) -- React requires the same hooks to run on every render of a
  // given mounted instance. A source pointed at while another activation is
  // already running stays mounted showing the blocking view, then re-renders
  // showing the normal picker the moment that activation finishes -- if the
  // hooks were declared after the early return (as they briefly were), that
  // transition would call useState/useAsync for the first time on a later
  // render and violates the Rules of Hooks (caught 2026-08-28, before it
  // ever shipped in a way that could actually crash a real session).
  const [browsePath, setBrowsePath] = useState<string | undefined>(undefined);
  const browse = useAsync(() => api.browse(browsePath), [browsePath]);
  const [jumpInput, setJumpInput] = useState("");
  const [nameInput, setNameInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmingRemoveId, setConfirmingRemoveId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // Set when the chosen folder's files are cloud-only -- see confirmFolder.
  const [notLocal, setNotLocal] = useState<{ path: string; info: NotLocalInfo } | null>(null);
  // Initial tab only -- deliberately not kept in sync with `sources` after
  // mount (this panel unmounts on a successful add/activate anyway, see
  // onActivationStarted, so there's no "should the tab jump under you"
  // case to handle).
  const [tab, setTab] = useState<"indexed" | "browse">(() => (sources.length > 0 ? "indexed" : "browse"));

  // The backend's activation lock is global (one shared live store, see
  // ingestion.activation), not per-source -- so any activation/rescan
  // already running (output OR input) blocks starting a new one. Show that
  // instead of the picker rather than letting them hit the 409 by trying.
  if (activation.activating) {
    return (
      <div className="datasource">
        <div className="datasource__intro">
          <h1 className="datasource__title">Loading in progress</h1>
          <p className="datasource__subtitle">
            “{activation.activating.name}” is still being loaded — wait for it to finish, or cancel it,
            before starting another.
          </p>
        </div>
        <section className="datasource__blocking">
          <div className="landing__tile-progress">
            <span className="badge badge--muted landing__tile-badge">
              ⏳ {activationLabel(activation.status)}
            </span>
            <span className="landing__tile-progress-track">
              <span
                className={
                  "landing__tile-progress-bar" +
                  (activation.status?.files_total ? "" : " landing__tile-progress-bar--indeterminate")
                }
                style={
                  activation.status?.files_total
                    ? {
                        width: `${Math.min(
                          100,
                          (activation.status.files_done / activation.status.files_total) * 100,
                        )}%`,
                      }
                    : undefined
                }
              />
            </span>
          </div>
          <button className="btn btn--ghost" onClick={activation.cancel}>
            Cancel
          </button>
        </section>
      </div>
    );
  }

  const jumpToPath = () => {
    if (jumpInput.trim()) setBrowsePath(jumpInput.trim());
  };

  // The one and only "commit" action for POINTING AT A NEW folder -- always
  // acts on whatever folder the browser is currently showing. Only covers
  // registration + kicking off ingestion (both fast: registration validates
  // by finding just the first real file, not scanning everything -- see
  // pipeline.py's validate_output_root/_any_output_csv); the actual, slow
  // ingestion work is handed off to onActivationStarted and tracked
  // elsewhere from here on.
  //
  // A folder whose files aren't on this computer yet (OneDrive "Files
  // On-Demand") is NOT an error: the backend registers nothing and answers
  // 409 not_local, and this shows what has to happen first instead --
  // "Download and scan" re-submits with keepLocal, which makes downloading
  // the first phase of the same tracked background job (progress on the
  // tile, Cancel, survives a page reload), then the scan runs by itself.
  const confirmFolder = async (path: string, keepLocal = false) => {
    setSubmitting(true);
    setActionError(null);
    const name = nameInput.trim() || path.split(/[\\/]/).filter(Boolean).pop() || path;
    try {
      const source = await api.addSource(name, path, kind, keepLocal);
      await api.activateSource(source.id);
      setNotLocal(null);
      onActivationStarted({ id: source.id, kind, name });
    } catch (e) {
      const info = asNotLocal(e);
      if (info) setNotLocal({ path, info });
      else setActionError((e as Error).message);
      setSubmitting(false);
    }
  };

  const useSource = async (source: DataSource) => {
    setBusyId(source.id);
    setActionError(null);
    try {
      await api.activateSource(source.id);
      onActivationStarted({ id: source.id, kind, name: source.name });
    } catch (e) {
      setActionError((e as Error).message);
      setBusyId(null);
    }
  };

  const rescanOneSource = async (source: DataSource) => {
    setBusyId(source.id);
    setActionError(null);
    try {
      await api.rescanSource(source.id);
      onActivationStarted({ id: source.id, kind, name: source.name });
    } catch (e) {
      setActionError((e as Error).message);
      setBusyId(null);
    }
  };

  const removeOneSource = async (source: DataSource) => {
    setBusyId(source.id);
    setActionError(null);
    try {
      await api.removeSource(source.id);
      setConfirmingRemoveId(null);
      onSourceRemoved();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusyId(null);
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

      <div className="datasource__tabs">
        <button
          className={`datasource__tab${tab === "indexed" ? " is-active" : ""}`}
          onClick={() => setTab("indexed")}
        >
          Indexed data
          {sources.length > 0 &&
            ` (${sources.length}) · ${formatBytes(sources.reduce((sum, s) => sum + s.cache_size_bytes, 0))} total`}
        </button>
        <button
          className={`datasource__tab${tab === "browse" ? " is-active" : ""}`}
          onClick={() => setTab("browse")}
        >
          Browse for a folder
        </button>
      </div>

      {tab === "indexed" && (
        <section className="datasource__loaded">
          {sources.length === 0 && (
            <p className="muted datasource__loaded-empty">
              Nothing indexed yet — switch to “Browse for a folder” to point at one.
            </p>
          )}
          {sources.map((source) => (
            <div
              className={`datasource__loaded-row${source.active ? " datasource__loaded-row--active" : ""}`}
              key={source.id}
            >
              <div className="datasource__loaded-title">
                <span className="datasource__loaded-name">
                  {source.name}
                  {source.active && <span className="badge badge--ok datasource__loaded-badge">Active now</span>}
                </span>
                {source.data_kind && DATA_KIND_META[source.data_kind] && (
                  <span className={`badge datasource__loaded-badge ${DATA_KIND_META[source.data_kind].className}`}>
                    {DATA_KIND_META[source.data_kind].icon} {DATA_KIND_META[source.data_kind].label}
                  </span>
                )}
              </div>
              <span className="muted mono datasource__loaded-path">{source.path}</span>
              <span
                className={
                  source.status === "error"
                    ? "datasource__loaded-meta datasource__loaded-meta--error"
                    : "muted datasource__loaded-meta"
                }
              >
                {source.status === "ok" && source.last_scanned_at
                  ? `Indexed: ${new Date(source.last_scanned_at).toLocaleString()} · ${formatBytes(source.cache_size_bytes)}`
                  : source.status === "error"
                    ? `Scan failed${source.error ? `: ${source.error}` : ""}`
                    : "Never scanned"}
              </span>
              {source.scan_warnings.length > 0 && (
                <ul className="datasource__warnings">
                  {source.scan_warnings.map((w) => (
                    <li key={w}>⚠ {w}</li>
                  ))}
                </ul>
              )}
              <div className="datasource__loaded-actions-row">
                {confirmingRemoveId === source.id ? (
                  <span className="datasource__loaded-confirm">
                    <span className="muted">Remove and delete its cache? A future reload needs a full re-scan.</span>
                    <button className="btn btn--danger" onClick={() => removeOneSource(source)} disabled={busyId === source.id}>
                      {busyId === source.id ? "Removing…" : "Yes, remove"}
                    </button>
                    <button
                      className="btn btn--ghost"
                      onClick={() => setConfirmingRemoveId(null)}
                      disabled={busyId === source.id}
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <span className="datasource__loaded-actions">
                    <span className="datasource__loaded-actions-group">
                      <button className="btn btn--ghost" onClick={() => rescanOneSource(source)} disabled={busyId !== null}>
                        {busyId === source.id
                          ? "Starting…"
                          : source.scan_duration_seconds != null
                            ? `Rescan (${formatDuration(source.scan_duration_seconds)})`
                            : "Rescan"}
                      </button>
                      <button
                        className="btn btn--danger"
                        onClick={() => setConfirmingRemoveId(source.id)}
                        disabled={busyId !== null}
                      >
                        Remove
                      </button>
                    </span>
                    {!source.active && source.status === "ok" && (
                      <button className="btn btn--success" onClick={() => useSource(source)} disabled={busyId !== null}>
                        {busyId === source.id ? "Starting…" : "Use this"}
                      </button>
                    )}
                  </span>
                )}
              </div>
            </div>
          ))}
        </section>
      )}

      {tab === "browse" && (
      <section className="datasource__section">
        <div className="datasource__pathrow">
          <input
            className="datasource__pathinput mono"
            placeholder="Jump to a path (e.g. Z:\Baltic Sea 2026-08)…"
            value={jumpInput}
            onChange={(e) => setJumpInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && jumpToPath()}
            disabled={submitting}
          />
          <button className="btn btn--ghost" onClick={jumpToPath} disabled={submitting || !jumpInput.trim()}>
            Go
          </button>
        </div>

        <div className="datasource__browser">
          {browse.loading && <div className="muted pad">Loading…</div>}
          {browse.error && <div className="error pad">{browse.error}</div>}
          {browse.data && (
            <>
              <div className="datasource__breadcrumb mono">
                {!browse.data.is_drives_list && (
                  <button className="badge badge--btn" onClick={() => setBrowsePath(DRIVES)} disabled={submitting}>
                    💻 This PC
                  </button>
                )}
                {browse.data.parent !== null && (
                  <button
                    className="badge badge--btn"
                    onClick={() => setBrowsePath(browse.data!.parent!)}
                    disabled={submitting}
                  >
                    .. up
                  </button>
                )}
                <span>{browse.data.path}</span>
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
                      disabled={submitting}
                    >
                      {browse.data!.is_drives_list ? "💽" : "📁"} {entry.name}
                      {entry.looks_like_source && (
                        <span className="badge badge--muted datasource__hint-badge">looks like a model export</span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
              {/* The one commit action for the whole panel -- always acts on
                  whichever folder is currently open above. Navigate by
                  clicking folder names; confirm here once you're looking at
                  the right one. Hidden for the synthetic "This PC" drives
                  list, which isn't itself a real folder to select. */}
              {notLocal && notLocal.path === browse.data.path && (
                <div className="datasource__notice">
                  <strong>This folder isn't on this computer yet</strong>
                  <p>
                    {notLocal.info.cloud_only_files.toLocaleString()} of its files (
                    {formatBytes(notLocal.info.cloud_only_bytes)}) are stored only online (OneDrive
                    “Files On-Demand”). They have to be downloaded to this computer before the data can be
                    scanned.
                  </p>
                  {notLocal.info.can_download ? (
                    <>
                      <p className="muted">
                        Download and scan asks OneDrive to keep this folder on this computer from now on (the
                        same as “Always keep on this device” in File Explorer), waits for the download, then
                        scans automatically. Progress is shown on the tile — you can leave this screen.
                      </p>
                      <div className="datasource__notice-actions">
                        <button className="btn" onClick={() => confirmFolder(notLocal.path, true)} disabled={submitting}>
                          {submitting ? "Starting…" : `Download (${formatBytes(notLocal.info.cloud_only_bytes)}) and scan`}
                        </button>
                        <button className="btn btn--ghost" onClick={() => setNotLocal(null)} disabled={submitting}>
                          Cancel
                        </button>
                      </div>
                    </>
                  ) : (
                    <p className="muted">
                      This server can't download them itself — make the files available as ordinary files in
                      this folder, then choose it again.
                    </p>
                  )}
                </div>
              )}
              {!browse.data.is_drives_list && !(notLocal && notLocal.path === browse.data.path) && (
                <div className="datasource__confirmbar">
                  <input
                    className="datasource__nameinput"
                    placeholder={browse.data.path.split(/[\\/]/).filter(Boolean).pop() ?? "Name"}
                    value={nameInput}
                    onChange={(e) => setNameInput(e.target.value)}
                    disabled={submitting}
                  />
                  <button
                    className="btn"
                    onClick={() => confirmFolder(browse.data!.path)}
                    disabled={submitting}
                  >
                    {submitting ? "Checking folder…" : "Use this folder"}
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
