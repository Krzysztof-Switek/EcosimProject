import { useEffect, useRef, useState } from "react";
import { api, type ActivationStatus } from "../../api/client";
import type { DataSource, DataSourceKind, ModelInventory } from "../../api/types";
import { activationLabel, type ActivatingSource } from "../datasource/useActivationTracker";

type Module = "spatial" | "timeseries";

// Matches IDENTIFY_VERSION in backend ingestion/model_origin.py: a source
// identified by an older version is identified again (2 = Ecopath group names,
// 3 = Ecopath baseline biomass).
const IDENTIFY_VERSION = 3;

const n = (x: number) => x.toLocaleString("en-US");
const plural = (x: number, one: string, many = `${one}s`) => `${n(x)} ${x === 1 ? one : many}`;

interface ModelRow {
  label: string;
  found: boolean;
  detail?: string;
}

/** Group names this source's Ecopath output provides (largest model's count). */
function groupCount(m: ModelInventory): number {
  return Math.max(0, ...Object.values(m.ecopath?.groups ?? {}).map((g) => Object.keys(g).length));
}

/** The rows a tile lists: for output, the three EwE model layers the files
 * came from; for input, the kinds of model input the manual describes (see
 * backend ingestion/model_origin.py and docs/ewe-data-formats.md). */
function modelRows(kind: DataSourceKind, m: ModelInventory, runCount: number): ModelRow[] {
  if (kind === "output") {
    const names = (xs: string[] | undefined, what: string) =>
      xs && xs.length > 0
        ? `${plural(xs.length, what)}: ${xs.slice(0, 2).join(", ")}${xs.length > 2 ? "…" : ""}`
        : undefined;
    return [
      {
        label: "Ecopath",
        found: !!m.ecopath,
        detail: m.ecopath
          ? [
              names(m.ecopath.models, "model"),
              groupCount(m) ? `names of ${plural(groupCount(m), "group")}` : null,
              Object.keys(m.ecopath.baseline_biomass ?? {}).length > 0 ? "baseline B0" : null,
            ]
              .filter(Boolean)
              .join(" · ")
          : undefined,
      },
      { label: "Ecosim", found: !!m.ecosim, detail: names(m.ecosim?.scenarios, "scenario") },
      {
        label: "Ecospace",
        found: !!m.ecospace,
        detail: m.ecospace
          ? [names(m.ecospace.scenarios, "scenario"), m.ecospace.maps ? plural(m.ecospace.maps, "map") : null]
              .filter(Boolean)
              .join(" · ")
          : undefined,
      },
      ...(runCount > 1 ? [{ label: "Runs", found: true, detail: `${n(runCount)} (Monte Carlo / multiple setups)` }] : []),
    ];
  }
  return [
    {
      label: "Ecopath model",
      found: !!m.ecopath_model,
      detail: m.ecopath_model ? m.ecopath_model.names.slice(0, 2).join(", ") : undefined,
    },
    {
      label: "Ecosim time series",
      found: !!m.ecosim_timeseries,
      detail: m.ecosim_timeseries
        ? `${plural(m.ecosim_timeseries.series, "series", "series")} in ${plural(m.ecosim_timeseries.files, "CSV", "CSVs")}`
        : undefined,
    },
    {
      label: "Ecospace input maps",
      found: !!m.ecospace_maps,
      detail: m.ecospace_maps
        ? [
            m.ecospace_maps.files ? plural(m.ecospace_maps.files, ".asc map") : null,
            m.ecospace_maps.shapefiles ? plural(m.ecospace_maps.shapefiles, "shapefile") : null,
          ]
            .filter(Boolean)
            .join(" · ")
        : undefined,
    },
    ...(m.driver_trends ? [{ label: "Driver trends", found: true, detail: plural(m.driver_trends.files, "file") }] : []),
  ];
}

/** Which models the active source's files come from -- what the rest of the
 * app can do next depends on it. */
function ModelList({ source, identifying }: { source: DataSource; identifying: boolean }) {
  if (!source.models) {
    return (
      <span className="modellist__pending muted">
        {identifying ? "Identifying models…" : "Models not identified yet"}
      </span>
    );
  }
  const rows = modelRows(source.kind, source.models, source.run_count);
  return (
    <span className="modellist" title={source.path}>
      <span className="modellist__source">{source.name}</span>
      {rows.map((r) => (
        <span key={r.label} className={`modellist__row${r.found ? " is-found" : ""}`}>
          <span className="modellist__mark" aria-hidden="true">{r.found ? "✓" : "–"}</span>
          <span className="modellist__label">{r.label}</span>
          {r.detail && <span className="modellist__detail">{r.detail}</span>}
        </span>
      ))}
      {source.models.not_checked > 0 && (
        <span className="modellist__note muted">
          {plural(source.models.not_checked, "file")} only in the cloud, not checked
        </span>
      )}
    </span>
  );
}

function SourceTile({
  kind,
  icon,
  arrow,
  title,
  desc,
  indexedCount,
  activeSource,
  identifying,
  onClick,
  activating,
  activatingStatus,
  canManage,
}: {
  kind: DataSourceKind;
  icon: string;
  arrow: "down" | "up";
  title: string;
  desc: string;
  // Count of ALL indexed sources of this kind, not just the active one --
  // naming the active source here stopped making sense once "Indexed data"
  // (DataSourcePanel) can hold several (2026-08-28): this tile's job is now
  // "is something loading" (progress) or "how much is indexed" (a count),
  // never which specific one is active -- that's the panel's job.
  indexedCount: number;
  /** The source of this kind in use -- its identified models are listed on the tile. */
  activeSource: DataSource | null;
  identifying: boolean;
  onClick: (kind: DataSourceKind) => void;
  activating: ActivatingSource | null;
  activatingStatus: ActivationStatus | null;
  canManage: boolean;
}) {
  const isActivatingThis = activating?.kind === kind;
  return (
    <button
      className="landing__tile landing__tile--upload landing__tile--source"
      onClick={() => onClick(kind)}
      disabled={!canManage}
      title={canManage ? undefined : MANAGED_BY_ADMIN}
    >
      <span className="landing__icon" aria-hidden="true">
        {icon}
        <span className={`landing__icon-arrow landing__icon-arrow--${arrow}`}>{arrow === "down" ? "⬇" : "⬆"}</span>
      </span>
      <span className="landing__tile-title">{title}</span>
      <span className="landing__tile-desc">{desc}</span>
      {isActivatingThis ? (
        <span className="landing__tile-progress">
          <span className="badge badge--muted landing__tile-badge">
            ⏳ {activationLabel(activatingStatus)}
          </span>
          <span className="landing__tile-progress-track">
            <span
              className={
                "landing__tile-progress-bar" +
                (activatingStatus?.files_total ? "" : " landing__tile-progress-bar--indeterminate")
              }
              style={
                activatingStatus?.files_total
                  ? { width: `${Math.min(100, (activatingStatus.files_done / activatingStatus.files_total) * 100)}%` }
                  : undefined
              }
            />
          </span>
        </span>
      ) : indexedCount > 0 ? (
        <>
          <span className="badge badge--ok landing__tile-badge">✓ {indexedCount} indexed</span>
          {activeSource ? (
            <ModelList source={activeSource} identifying={identifying} />
          ) : (
            <span className="modellist__pending muted">None in use — click to choose one</span>
          )}
        </>
      ) : (
        <span className="badge badge--muted landing__tile-badge">Not set — click to choose</span>
      )}
    </button>
  );
}

/**
 * Ecopath data (optional) -- deliberately NOT a SourceTile: the official EwE
 * manuals document no folder/file export convention for Ecopath's own data
 * at all (verified 2026-08-28 -- the only documented sharing mechanism is a
 * whole-model export to the online Ecobase repository, UG p.6; see
 * docs/ewe-data-formats.md's "Czy dane Ecopath mają eksportowalną-do-folderu
 * konwencję" section). Wiring this up as a third folder-scanning tile like
 * output/input would mean inventing a convention EwE itself doesn't have.
 * Stays an honest, inert placeholder -- same pattern as the Monte Carlo
 * tile's "In progress" badge -- until there's a real sample of what this
 * data actually looks like to design against.
 */
function EcopathStubTile() {
  return (
    <div className="landing__tile landing__tile--upload landing__tile--stub" title="Not supported yet">
      <span className="landing__icon" aria-hidden="true">🧮</span>
      <span className="landing__tile-title">Ecopath data</span>
      <span className="landing__tile-desc">Static base model (optional)</span>
      <span className="badge badge--muted landing__tile-badge">Not supported yet</span>
    </div>
  );
}

const MANAGED_BY_ADMIN = "Only the administrator can change this.";

/** Reference areas (optional): ICES / management region maps on the model's
 * grid, used by analyses -- see features/regions/ReferenceAreasPanel.tsx. */
function ReferenceAreasTile({
  packs,
  layers,
  onClick,
  canManage,
}: {
  packs: number;
  layers: number;
  onClick: () => void;
  canManage: boolean;
}) {
  return (
    <button
      className="landing__tile landing__tile--upload landing__tile--source"
      onClick={onClick}
      disabled={!canManage}
      title={canManage ? undefined : MANAGED_BY_ADMIN}
    >
      <span className="landing__icon" aria-hidden="true">🧭</span>
      <span className="landing__tile-title">Reference areas</span>
      <span className="landing__tile-desc">ICES and management areas for analyses (optional)</span>
      {packs > 0 ? (
        <span className="badge badge--ok landing__tile-badge">
          ✓ {packs} loaded · {layers} layer{layers === 1 ? "" : "s"}
        </span>
      ) : (
        <span className="badge badge--muted landing__tile-badge">Not set — click to choose</span>
      )}
    </button>
  );
}

export function Landing({
  onSelect,
  onOpenSource,
  activeOutput,
  activeInput,
  onSourcesChanged,
  outputCount,
  inputCount,
  activating,
  activatingStatus,
  referenceAreas,
  onOpenReferenceAreas,
  canManage,
}: {
  onSelect: (m: Module) => void;
  onOpenSource: (kind: DataSourceKind) => void;
  activeOutput: DataSource | null;
  activeInput: DataSource | null;
  /** A source's details changed (here: its models were identified) -- refetch the list. */
  onSourcesChanged: () => void;
  outputCount: number;
  inputCount: number;
  activating: ActivatingSource | null;
  activatingStatus: ActivationStatus | null;
  referenceAreas: { packs: number; layers: number };
  onOpenReferenceAreas: () => void;
  /** Data sources and reference areas can be changed (not a tester's account). */
  canManage: boolean;
}) {
  const ready = activeOutput !== null;
  // Gated on what the last scan actually found (data_kind), not just
  // "is any output active" -- see ingestion.activation._data_kind. Monte
  // Carlo data opens the same two views, marked as such on their tiles: they
  // tell its runs apart (the baseline run with the samples' 5–95% band, or one
  // run -- catalog/runs.py), each where the identified models say the data has
  // Ecospace / Ecosim output.
  const kind = activeOutput?.data_kind ?? null;
  const models = activeOutput?.models;
  const monteCarlo = ready && kind === "montecarlo";
  const spatialReady = ready && (kind === "spatial" || kind === "mixed" || (monteCarlo && !!models?.ecospace));
  const timeseriesReady =
    ready && (kind === "timeseries" || kind === "mixed" || (monteCarlo && !!models?.ecosim));
  const mcBadge = (ok: boolean) =>
    monteCarlo && ok ? (
      <span className="badge badge--kind-montecarlo landing__tile-badge">
        🎲 Monte Carlo · {activeOutput!.run_count} runs
      </span>
    ) : null;
  const mcIcon = monteCarlo ? (
    <span className="landing__icon-mc" title="Monte Carlo data">
      🎲
    </span>
  ) : null;

  // Sources scanned before model identification existed (or identified by an
  // older version of it) have none / less recorded -- identify them now (reads only file headers, skips cloud-only files: under
  // a second for one run, ~25 s for a large Monte Carlo folder). Once per
  // source per visit; every new scan records it itself.
  const [identifying, setIdentifying] = useState<Set<string>>(new Set());
  const tried = useRef(new Set<string>());
  useEffect(() => {
    for (const s of [activeOutput, activeInput]) {
      if (!canManage) break; // identifying records it on the source -- an administrator's change
      if (!s || s.models?.version === IDENTIFY_VERSION || s.status !== "ok" || tried.current.has(s.id)) continue;
      tried.current.add(s.id);
      setIdentifying((prev) => new Set(prev).add(s.id));
      api
        .identifySource(s.id)
        .then(onSourcesChanged)
        .catch(() => {}) // the tile keeps saying "not identified yet"
        .finally(() =>
          setIdentifying((prev) => {
            const next = new Set(prev);
            next.delete(s.id);
            return next;
          }),
        );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOutput?.id, activeOutput?.models, activeInput?.id, activeInput?.models]);

  return (
    <div className="landing">
      <div className="landing__intro">
        <p className="landing__subtitle">
          {ready
            ? "Choose what you want to work with."
            : "Step 1: point the Explorer at your model data before anything else works."}
        </p>
      </div>

      <div className="landing__row">
        <span className="landing__row-label">1. Required data</span>
        <div className="landing__tiles">
          <SourceTile
            kind="output"
            icon="📊"
            arrow="up"
            title="Model output data"
            desc="Results of Ecopath, Ecosim and Ecospace runs"
            indexedCount={outputCount}
            activeSource={activeOutput}
            identifying={!!activeOutput && identifying.has(activeOutput.id)}
            onClick={onOpenSource}
            activating={activating}
            activatingStatus={activatingStatus}
            canManage={canManage}
          />
          <SourceTile
            kind="input"
            icon="🛰️"
            arrow="down"
            title="Model input data"
            desc="Model file, time series and maps the model runs on"
            indexedCount={inputCount}
            activeSource={activeInput}
            identifying={!!activeInput && identifying.has(activeInput.id)}
            onClick={onOpenSource}
            activating={activating}
            activatingStatus={activatingStatus}
            canManage={canManage}
          />
        </div>
      </div>

      <div className="landing__row">
        <span className="landing__row-label">2. Optional data</span>
        <div className="landing__tiles">
          <ReferenceAreasTile
            packs={referenceAreas.packs}
            layers={referenceAreas.layers}
            onClick={onOpenReferenceAreas}
            canManage={canManage}
          />
          <EcopathStubTile />
        </div>
      </div>

      <div className="landing__row">
        <span className="landing__row-label">3. Explore</span>
        <div className="landing__tiles">
          <button
            className={`landing__tile${monteCarlo ? " landing__tile--mc" : ""}`}
            onClick={() => onSelect("spatial")}
            disabled={!spatialReady}
          >
            <span className="landing__icon landing__icon--mc-host" aria-hidden="true">
              🗺️{mcIcon}
            </span>
            <span className="landing__tile-title">Spatial data</span>
            <span className="landing__tile-desc">
              {monteCarlo ? "Ecospace maps (.asc) of one run at a time" : "Ecospace maps (.asc)"}
            </span>
            {mcBadge(spatialReady)}
            {!spatialReady && (
              <span className="badge badge--muted landing__tile-badge">
                {!ready ? "🔒 Needs output data" : "🔒 Needs Ecospace output"}
              </span>
            )}
          </button>
          <button
            className={`landing__tile${monteCarlo ? " landing__tile--mc" : ""}`}
            onClick={() => onSelect("timeseries")}
            disabled={!timeseriesReady}
          >
            <span className="landing__icon landing__icon--mc-host" aria-hidden="true">
              📈{mcIcon}
            </span>
            <span className="landing__tile-title">Time series</span>
            <span className="landing__tile-desc">
              {monteCarlo ? "Baseline run with the samples' 5–95% band" : <>Ecosim results (CSV) &amp; drivers</>}
            </span>
            {mcBadge(timeseriesReady)}
            {!timeseriesReady && (
              <span className="badge badge--muted landing__tile-badge">
                {!ready ? "🔒 Needs output data" : "🔒 Needs Ecosim output"}
              </span>
            )}
          </button>
        </div>
        {!ready && (
          <p className="muted landing__row-note">Set “Model output data” above to unlock these.</p>
        )}
      </div>
    </div>
  );
}
