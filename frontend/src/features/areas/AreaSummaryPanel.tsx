import { useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { SavedArea, ZonalRequest, ZonalResult, ZonalRow } from "../../api/types";
import { AOI_OUTLINE_COLORS } from "../spatial/RasterMap";
import { formatBytes, formatDuration, useZonal, type ZonalState } from "./useZonal";

type Stat = "mean" | "total";

const DASHES = ["", "6 3", "2 3", "8 3 2 3"];

function fmt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e6 || a < 1e-3)) return v.toExponential(3);
  return v.toLocaleString("en-US", { maximumSignificantDigits: 5 });
}

function seriesKey(r: { area_id: string; entity: string | null }) {
  return `${r.area_id}|${r.entity ?? ""}`;
}

/** One row per year, a value (and band) column per area x group/fleet -- for the chart and the CSV. */
function pivot(result: ZonalResult, stat: Stat) {
  const byYear = new Map<number, Record<string, number | number[] | null>>();
  const keys = new Map<string, { area: string; entity: string | null }>();
  for (const r of result.rows) {
    const k = seriesKey(r);
    keys.set(k, { area: r.area_id, entity: r.entity });
    const row = byYear.get(r.year) ?? { year: r.year };
    row[k] = (r[stat] as number | null | undefined) ?? null;
    const lo = r[`${stat}_p05` as keyof ZonalRow] as number | null | undefined;
    const hi = r[`${stat}_p95` as keyof ZonalRow] as number | null | undefined;
    if (lo != null && hi != null) row[`${k}|band`] = [lo, hi];
    byYear.set(r.year, row);
  }
  return { data: [...byYear.values()].sort((a, b) => Number(a.year) - Number(b.year)), keys };
}

function csvOf(result: ZonalResult, areaNames: Map<string, string>, label: string): string {
  const band = result.rows.some((r) => r.n_samples);
  const head = ["area", "group_or_fleet", "year", "mean", ...(result.semantics === "density" ? ["total"] : []),
    ...(band ? ["mean_p05", "mean_p95", ...(result.semantics === "density" ? ["total_p05", "total_p95"] : []), "n_samples"] : []),
    "cells_with_value", "coverage"];
  const q = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const lines = [`# ${label}; mean = area-weighted over the area's cells that have a value` +
    (result.semantics === "density" ? "; total = sum of value x cell area (km2)" : ""), head.join(",")];
  for (const r of result.rows) {
    const vals: (string | number | null | undefined)[] = [areaNames.get(r.area_id) ?? r.area_id, r.entity ?? "", r.year, r.mean,
      ...(result.semantics === "density" ? [r.total] : []),
      ...(band ? [r.mean_p05, r.mean_p95, ...(result.semantics === "density" ? [r.total_p05, r.total_p95] : []), r.n_samples] : []),
      r.n_cells, r.coverage];
    lines.push(vals.map((v) => (v == null ? "" : q(String(v)))).join(","));
  }
  return lines.join("\n") + "\n";
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * The variable summarised over each checked area, year by year (backend
 * regions/zonal.py): the area-weighted mean, and for densities the total.
 * For Monte Carlo maps: the run on the map, or every run (the baseline with
 * the samples' 5-95% band) -- which may mean downloading many maps first, so
 * that waits for the user's go-ahead with its cost shown.
 */
export function AreaSummaryPanel({
  scenario,
  variable,
  variableLabel,
  entities,
  yearFrom,
  yearTo,
  run,
  isMonteCarlo,
  areas,
  fixedRun,
  title = "Area summary",
  note,
}: {
  scenario: string;
  variable: string;
  variableLabel: string;
  entities: string[];
  yearFrom: number;
  yearTo: number;
  run: string | undefined;
  isMonteCarlo: boolean;
  areas: SavedArea[];
  /** Set by a view with its own run choice (Time series): a run_id, or "all"
   * for the baseline + band; no run radio is shown then. */
  fixedRun?: string;
  title?: string;
  /** Shown under the title (e.g. that these are aggregates of maps). */
  note?: string;
}) {
  const [open, setOpen] = useState(true);
  const [allRuns, setAllRuns] = useState(false);
  const [stat, setStat] = useState<Stat>("mean");

  const request: ZonalRequest | null = useMemo(
    () =>
      open && areas.length > 0
        ? {
            scenario,
            variable,
            areas,
            entities,
            year_from: yearFrom,
            year_to: yearTo,
            run: isMonteCarlo ? (fixedRun ?? (allRuns ? "all" : run)) : undefined,
          }
        : null,
    [open, scenario, variable, areas, entities, yearFrom, yearTo, isMonteCarlo, allRuns, run, fixedRun],
  );
  const { state, start, cancel, retry } = useZonal(request);

  return (
    <section className="areasummary">
      <div className="areasummary__head">
        <button className="areasummary__toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? "▾" : "▸"} {title}
        </button>
        <span className="muted">
          {variableLabel} · {areas.length} area{areas.length === 1 ? "" : "s"} · {yearFrom}–{yearTo}
        </span>
        {open && isMonteCarlo && fixedRun === undefined && (
          <span className="areasummary__runs">
            <label className="check">
              <input type="radio" checked={!allRuns} onChange={() => setAllRuns(false)} />
              Run on the map
            </label>
            <label className="check">
              <input type="radio" checked={allRuns} onChange={() => setAllRuns(true)} />
              All runs (baseline + 5–95% band)
            </label>
          </span>
        )}
      </div>
      {open && note && <div className="muted areasummary__note">{note}</div>}
      {open && (
        <SummaryBody
          state={state}
          stat={stat}
          onStat={setStat}
          onStart={start}
          onCancel={cancel}
          onRetry={retry}
          variableLabel={variableLabel}
          scenario={scenario}
        />
      )}
    </section>
  );
}

function SummaryBody({
  state,
  stat,
  onStat,
  onStart,
  onCancel,
  onRetry,
  variableLabel,
  scenario,
}: {
  state: ZonalState;
  stat: Stat;
  onStat: (s: Stat) => void;
  onStart: () => void;
  onCancel: () => void;
  onRetry: () => void;
  variableLabel: string;
  scenario: string;
}) {
  if (state.kind === "idle" || state.kind === "loading") return <div className="muted pad">Summarising…</div>;
  if (state.kind === "error") {
    return (
      <div className="error pad">
        {state.message}{" "}
        <button className="linkbtn" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }
  if (state.kind === "confirm") {
    const c = state.cost;
    return (
      <div className="areasummary__confirm">
        <p>
          This needs {c.maps.toLocaleString("en-US")} maps
          {c.maps_cached > 0 && ` (${c.maps_cached.toLocaleString("en-US")} already summarised)`}.{" "}
          {c.maps_to_download > 0 ? (
            <>
              {c.maps_to_download.toLocaleString("en-US")} of them are stored only online and will be downloaded first —{" "}
              <strong>{formatBytes(c.bytes_to_download)}</strong>. They are kept, so this is paid only once.
            </>
          ) : (
            <>All of them are on this computer.</>
          )}{" "}
          Estimated time: about <strong>{formatDuration(c.seconds_estimate)}</strong>.
        </p>
        {c.sync_app_missing && (
          <p className="aoilist__problem">
            {c.sync_app_missing} isn't running, so the maps stored only online can't be downloaded now — start it
            first, or Start anyway to summarise only the maps on this computer.
          </p>
        )}
        <button className="btn" onClick={onStart}>
          Start
        </button>
      </div>
    );
  }
  if (state.kind === "running") {
    const j = state.job;
    const pct = j.total > 0 ? Math.round((100 * j.done) / j.total) : 0;
    const what =
      j.phase === "downloading"
        ? `Downloading maps — ${formatBytes(j.done)} of ${formatBytes(j.total)}`
        : j.phase === "reading"
          ? `Reading maps — ${j.done.toLocaleString("en-US")} of ${j.total.toLocaleString("en-US")}`
          : "Starting…";
    return (
      <div className="areasummary__progress">
        <div>
          {what}
          {j.paused && <span className="aoilist__problem"> — waiting for the sync app to serve files again</span>}
        </div>
        <div className="areasummary__bar">
          <div style={{ width: `${pct}%` }} />
        </div>
        <button className="btn btn--ghost" onClick={onCancel}>
          Stop (keeps what is done)
        </button>
      </div>
    );
  }
  return (
    <SummaryResult result={state.result} stat={stat} onStat={onStat} variableLabel={variableLabel} scenario={scenario} />
  );
}

function SummaryResult({
  result,
  stat,
  onStat,
  variableLabel,
  scenario,
}: {
  result: ZonalResult;
  stat: Stat;
  onStat: (s: Stat) => void;
  variableLabel: string;
  scenario: string;
}) {
  const shown: Stat = result.semantics === "density" ? stat : "mean";
  const { data, keys } = useMemo(() => pivot(result, shown), [result, shown]);
  const areaIndex = new Map(result.areas.map((a, i) => [a.id, i]));
  const areaNames = new Map(result.areas.map((a) => [a.id, a.name]));
  const entities = [...new Set([...keys.values()].map((k) => k.entity))];
  const band = result.rows.some((r) => r.n_samples);
  const coverage = result.areas.map((a) => {
    const r = result.rows.find((x) => x.area_id === a.id);
    return { ...a, coverage: r?.coverage ?? null };
  });

  return (
    <div className="areasummary__result">
      <div className="areasummary__controls">
        {result.semantics === "density" ? (
          <>
            <label className="check">
              <input type="radio" checked={shown === "mean"} onChange={() => onStat("mean")} />
              Mean (per km²)
            </label>
            <label className="check">
              <input type="radio" checked={shown === "total"} onChange={() => onStat("total")} />
              Total over the area
            </label>
          </>
        ) : (
          <span className="muted">
            Area-weighted mean
            {result.semantics === "indicator" && " (a sum over cells isn't meaningful for this indicator)"}
          </span>
        )}
        <button
          className="linkbtn areasummary__csv"
          onClick={() =>
            download(`area_summary__${scenario}__${result.variable}.csv`, csvOf(result, areaNames, `${variableLabel}, ${scenario}`))
          }
        >
          Download CSV
        </button>
      </div>
      {result.rows.length === 0 ? (
        <div className="muted pad">No values in these areas.</div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="year" />
            <YAxis tickFormatter={fmt} width={70} />
            <Tooltip formatter={(v: unknown) => (Array.isArray(v) ? `${fmt(v[0])} – ${fmt(v[1])}` : fmt(v as number))} />
            <Legend />
            {[...keys.entries()].flatMap(([k, { area, entity }]) => {
              const color = AOI_OUTLINE_COLORS[(areaIndex.get(area) ?? 0) % AOI_OUTLINE_COLORS.length];
              const name = `${areaNames.get(area) ?? area}${entity ? ` · ${entity}` : ""}`;
              const dash = DASHES[entities.indexOf(entity) % DASHES.length];
              return [
                ...(band
                  ? [
                      <Area
                        key={`${k}|band`}
                        dataKey={`${k}|band`}
                        name={`${name} (5–95%)`}
                        stroke="none"
                        fill={color}
                        fillOpacity={0.15}
                        legendType="none"
                        isAnimationActive={false}
                      />,
                    ]
                  : []),
                <Line
                  key={k}
                  dataKey={k}
                  name={name}
                  stroke={color}
                  strokeDasharray={dash}
                  dot={false}
                  strokeWidth={2}
                  isAnimationActive={false}
                />,
              ];
            })}
          </ComposedChart>
        </ResponsiveContainer>
      )}
      <div className="areasummary__notes muted">
        {coverage.map((a) => (
          <span key={a.id}>
            {a.name}: {a.cells.toLocaleString("en-US")} cells, {Math.round(a.area_km2).toLocaleString("en-US")} km²
            {a.coverage != null && a.coverage < 0.999 && ` — model values in ${Math.round(a.coverage * 100)}% of them`}
          </span>
        ))}
        {band && <span>Line: baseline run; band: 5th–95th percentile over the Monte Carlo samples.</span>}
        {result.maps_missing > 0 && (
          <span className="aoilist__problem">
            {result.maps_missing.toLocaleString("en-US")} of {result.maps.toLocaleString("en-US")} maps are left out
            {result.problems?.length ? ":" : "."}
          </span>
        )}
        {result.cancelled && <span className="aoilist__problem">Stopped before the end — showing what was done.</span>}
        {result.problems?.slice(0, 3).map((p) => (
          <span key={p} className="aoilist__problem">
            {p}
          </span>
        ))}
      </div>
    </div>
  );
}
