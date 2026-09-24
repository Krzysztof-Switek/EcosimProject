import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { ActivationStatus } from "../../api/client";
import type { DataSourceKind } from "../../api/types";

const STORAGE_KEY = "ecosim.activatingSource";
const POLL_INTERVAL_MS = 1000;

export interface ActivatingSource {
  id: string;
  kind: DataSourceKind;
  name: string;
}

// Human labels for the backend's progress phases (ingestion.pipeline.ProgressFn) --
// see backend/ecosim/ingestion/pipeline.py/spatial_pipeline.py for where each fires.
export const PHASE_LABEL: Record<string, string> = {
  starting: "Starting",
  downloading: "Downloading to this computer",
  checking_files: "Checking files are on this computer",
  discovering_output: "Scanning output files",
  output: "Loading output data",
  input: "Loading input data",
  discovering_rasters: "Scanning spatial maps",
  rasters: "Indexing spatial maps",
  catalog: "Building catalog",
  done: "Done",
};

/** Compact one-line summary, shared by the Landing tile and the app-bar pill. */
export function activationLabel(status: ActivationStatus | null): string {
  if (!status) return "Starting…";
  const phase = PHASE_LABEL[status.phase ?? ""] ?? status.phase ?? "Working";
  // "downloading" reports bytes, not files (see backend activation.py's
  // _download_to_this_computer).
  if (status.phase === "downloading" && status.files_total) {
    const gb = (n: number) => (n / 1024 ** 3).toFixed(1); // 1024-based, like File Explorer
    return `${phase}… ${gb(status.files_done)} / ${gb(status.files_total)} GB`;
  }
  if (status.files_total) {
    return `${phase}… ${status.files_done.toLocaleString()}/${status.files_total.toLocaleString()}`;
  }
  if (status.files_done > 0) return `${phase}… (${status.files_done.toLocaleString()} scanned)`;
  return `${phase}…`;
}

function loadStored(): ActivatingSource | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ActivatingSource) : null;
  } catch {
    return null;
  }
}

function persist(source: ActivatingSource | null) {
  try {
    if (source) localStorage.setItem(STORAGE_KEY, JSON.stringify(source));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* best-effort only -- losing this just means progress won't survive a page reload */
  }
}

/**
 * Tracks a background source activation across navigation *and* full page
 * reloads -- ingestion runs on the backend independently of the frontend
 * (see backend/ecosim/ingestion/activation.py's start_activation), so
 * there's no reason polling has to live and die with whichever screen
 * happened to start it. Previously this lived entirely inside
 * DataSourcePanel, so navigating away (or the panel unmounting) threw away
 * all visibility into a still-running activation even though the backend
 * kept working -- moved up to App.tsx 2026-08-28 so progress stays visible
 * on the Landing tile and the app bar regardless of which screen is open.
 * `localStorage` persistence means a page reload mid-activation resumes
 * polling instead of losing track of it entirely.
 */
export function useActivationTracker(onDone: () => void) {
  const [activating, setActivating] = useState<ActivatingSource | null>(loadStored);
  const [status, setStatus] = useState<ActivationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  const start = (source: ActivatingSource) => {
    setError(null);
    setStatus(null);
    persist(source);
    setActivating(source);
  };

  useEffect(() => {
    if (!activating) return;
    let stopped = false;
    const tick = async () => {
      if (stopped) return;
      try {
        const s = await api.activationStatus(activating.id);
        if (stopped) return;
        if (s.status === "unknown") {
          // Backend restarted (or never tracked this id) -- can't know
          // whether the job actually finished, just stop tracking quietly
          // rather than polling forever or claiming a false error.
          persist(null);
          setActivating(null);
          return;
        }
        setStatus(s);
        if (s.status === "ok") {
          persist(null);
          setActivating(null);
          onDoneRef.current();
          return;
        }
        if (s.status === "error") {
          setError(s.error ?? "Activation failed");
          persist(null);
          setActivating(null);
          return;
        }
        if (s.status === "cancelled") {
          // Not an error -- the user asked to stop. No message to show;
          // whatever was active before is untouched (see activation.py).
          persist(null);
          setActivating(null);
          return;
        }
        setTimeout(tick, POLL_INTERVAL_MS);
      } catch (e) {
        if (!stopped) {
          setError((e as Error).message);
          persist(null);
          setActivating(null);
        }
      }
    };
    tick();
    return () => {
      stopped = true;
    };
  }, [activating?.id]);

  const cancel = async () => {
    if (!activating) return;
    try {
      await api.cancelActivation(activating.id);
      // Don't stop tracking here: the backend still needs a checkpoint or
      // two to actually observe the cancel flag (see pipeline.py's
      // _PROGRESS_EVERY) -- let the next poll tick pick up status
      // "cancelled" the same way it picks up "ok"/"error", so the UI
      // reflects what actually happened rather than assuming success.
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return { activating, status, error, start, cancel, dismissError: () => setError(null) };
}
