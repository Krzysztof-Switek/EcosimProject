import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { ZonalCost, ZonalJob, ZonalRequest, ZonalResult } from "../../api/types";

const REQUEST_DELAY_MS = 400;
const POLL_MS = 1000;

export type ZonalState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "confirm"; cost: ZonalCost }
  | { kind: "running"; job: ZonalJob }
  | { kind: "done"; result: ZonalResult }
  | { kind: "error"; message: string };

/**
 * A variable summarised over areas (POST /spatial/zonal), asked again whenever
 * the request changes. Small requests come back at once; a large one (maps to
 * download, e.g. every Monte Carlo sample) waits in "confirm" with its cost
 * until ``start()``, then runs as a background job polled for progress.
 */
export function useZonal(request: ZonalRequest | null) {
  const [state, setState] = useState<ZonalState>({ kind: "idle" });
  const key = request ? JSON.stringify(request) : "";
  const requestRef = useRef(request);
  requestRef.current = request;
  const generation = useRef(0);

  const poll = useCallback((job: ZonalJob, gen: number) => {
    const tick = () => {
      if (generation.current !== gen) return;
      api.zonalJob(job.id).then(
        (j) => {
          if (generation.current !== gen) return;
          if (j.status === "running") {
            setState({ kind: "running", job: j });
            setTimeout(tick, POLL_MS);
          } else if (j.status === "error") {
            setState({ kind: "error", message: j.error ?? "The summary failed." });
          } else if (j.result) {
            setState({ kind: "done", result: j.result });
          }
        },
        (err: Error) => generation.current === gen && setState({ kind: "error", message: err.message }),
      );
    };
    setTimeout(tick, POLL_MS);
  }, []);

  const send = useCallback(
    (start: boolean) => {
      const req = requestRef.current;
      if (!req) return;
      const gen = ++generation.current;
      setState({ kind: "loading" });
      api.zonal({ ...req, start }).then(
        (res) => {
          if (generation.current !== gen) return;
          if (res.status === "done") setState({ kind: "done", result: res.result });
          else if (res.status === "confirm") setState({ kind: "confirm", cost: res.cost });
          else {
            setState({ kind: "running", job: res.job });
            poll(res.job, gen);
          }
        },
        (err: Error) => generation.current === gen && setState({ kind: "error", message: err.message }),
      );
    },
    [poll],
  );

  useEffect(() => {
    if (!key) {
      generation.current++;
      setState({ kind: "idle" });
      return;
    }
    const timer = setTimeout(() => send(false), REQUEST_DELAY_MS);
    return () => clearTimeout(timer);
  }, [key, send]);

  const cancel = useCallback(() => {
    if (state.kind === "running") void api.cancelZonalJob(state.job.id);
  }, [state]);

  return { state, start: () => send(true), cancel, retry: () => send(false) };
}

export function formatBytes(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(0)} MB`;
  return `${Math.max(1, Math.round(n / 1e3))} KB`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} s`;
  const m = Math.round(seconds / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}
