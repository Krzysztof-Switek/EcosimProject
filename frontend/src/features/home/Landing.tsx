import type { ActivationStatus } from "../../api/client";
import type { DataSource, DataSourceKind } from "../../api/types";
import { activationLabel, type ActivatingSource } from "../datasource/useActivationTracker";

type Module = "spatial" | "timeseries" | "montecarlo";

function SourceTile({
  kind,
  icon,
  arrow,
  title,
  desc,
  indexedCount,
  onClick,
  activating,
  activatingStatus,
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
  onClick: (kind: DataSourceKind) => void;
  activating: ActivatingSource | null;
  activatingStatus: ActivationStatus | null;
}) {
  const isActivatingThis = activating?.kind === kind;
  return (
    <button className="landing__tile landing__tile--upload" onClick={() => onClick(kind)}>
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
        <span className="badge badge--ok landing__tile-badge">✓ {indexedCount} indexed</span>
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

export function Landing({
  onSelect,
  onOpenSource,
  activeOutput,
  outputCount,
  inputCount,
  activating,
  activatingStatus,
}: {
  onSelect: (m: Module) => void;
  onOpenSource: (kind: DataSourceKind) => void;
  activeOutput: DataSource | null;
  outputCount: number;
  inputCount: number;
  activating: ActivatingSource | null;
  activatingStatus: ActivationStatus | null;
}) {
  const ready = activeOutput !== null;
  // Gated on what the last scan actually found (data_kind), not just
  // "is any output active" -- see ingestion.activation._data_kind. A
  // Monte Carlo dataset should not open the ordinary Spatial/Time series
  // views (misleading multi-run comparisons rendered as if single-run),
  // and vice versa the Monte Carlo view has nothing to show without
  // multi-run data -- see docs/Plans and TO_DO lists/28.08_session_summary.md.
  const kind = activeOutput?.data_kind ?? null;
  const spatialReady = ready && (kind === "spatial" || kind === "mixed");
  const timeseriesReady = ready && (kind === "timeseries" || kind === "mixed");
  const monteCarloReady = ready && kind === "montecarlo";

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
        <div className="landing__tiles landing__tiles--single">
          <SourceTile
            kind="output"
            icon="📊"
            arrow="up"
            title="Model output data"
            desc="Ecosim/Ecospace results (required)"
            indexedCount={outputCount}
            onClick={onOpenSource}
            activating={activating}
            activatingStatus={activatingStatus}
          />
        </div>
      </div>

      <div className="landing__row">
        <span className="landing__row-label">2. Optional data</span>
        <div className="landing__tiles">
          <SourceTile
            kind="input"
            icon="🛰️"
            arrow="down"
            title="Model input data"
            desc="Driver/forcing grids (optional)"
            indexedCount={inputCount}
            onClick={onOpenSource}
            activating={activating}
            activatingStatus={activatingStatus}
          />
          <EcopathStubTile />
        </div>
      </div>

      <div className="landing__row">
        <span className="landing__row-label">3. Explore</span>
        <div className="landing__tiles">
          <button className="landing__tile" onClick={() => onSelect("spatial")} disabled={!spatialReady}>
            <span className="landing__icon" aria-hidden="true">🗺️</span>
            <span className="landing__tile-title">Spatial data</span>
            <span className="landing__tile-desc">Ecospace ASCII maps (.asc)</span>
            {!spatialReady && (
              <span className="badge badge--muted landing__tile-badge">
                {!ready ? "🔒 Needs output data" : "🔒 Loaded data has no spatial maps"}
              </span>
            )}
          </button>
          <button className="landing__tile" onClick={() => onSelect("timeseries")} disabled={!timeseriesReady}>
            <span className="landing__icon" aria-hidden="true">📈</span>
            <span className="landing__tile-title">Time series</span>
            <span className="landing__tile-desc">Ecosim CSV output &amp; drivers</span>
            {!timeseriesReady && (
              <span className="badge badge--muted landing__tile-badge">
                {!ready ? "🔒 Needs output data" : "🔒 Loaded data has no time series"}
              </span>
            )}
          </button>
          <button className="landing__tile" onClick={() => onSelect("montecarlo")} disabled={!monteCarloReady}>
            <span className="landing__icon" aria-hidden="true">🎲</span>
            <span className="landing__tile-title">Monte Carlo</span>
            <span className="landing__tile-desc">Same scenario across multiple setups</span>
            {monteCarloReady ? (
              <span className="badge badge--ok landing__tile-badge">
                ✓ {activeOutput!.name} ({activeOutput!.run_count} samples)
              </span>
            ) : (
              <span className="badge badge--muted landing__tile-badge">
                {!ready ? "🔒 Needs output data" : "🔒 Loaded data is not Monte Carlo"}
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
