import type { DataSource, DataSourceKind } from "../../api/types";

type Module = "spatial" | "timeseries" | "montecarlo";

function SourceTile({
  kind,
  icon,
  arrow,
  title,
  desc,
  source,
  onClick,
}: {
  kind: DataSourceKind;
  icon: string;
  arrow: "down" | "up";
  title: string;
  desc: string;
  source: DataSource | null;
  onClick: (kind: DataSourceKind) => void;
}) {
  return (
    <button className="landing__tile landing__tile--upload" onClick={() => onClick(kind)}>
      <span className="landing__icon" aria-hidden="true">
        {icon}
        <span className={`landing__icon-arrow landing__icon-arrow--${arrow}`}>{arrow === "down" ? "⬇" : "⬆"}</span>
      </span>
      <span className="landing__tile-title">{title}</span>
      <span className="landing__tile-desc">{desc}</span>
      {source ? (
        <span className="badge badge--ok landing__tile-badge">✓ {source.name}</span>
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
}: {
  onSelect: (m: Module) => void;
  onOpenSource: (kind: DataSourceKind) => void;
  activeOutput: DataSource | null;
  activeInput: DataSource | null;
}) {
  const ready = activeOutput !== null;

  return (
    <div className="landing">
      <div className="landing__intro">
        <h1 className="landing__title">Ecosim Results Explorer</h1>
        <p className="landing__subtitle">
          {ready
            ? "Choose what you want to work with."
            : "Step 1: point the Explorer at your model data before anything else works."}
        </p>
      </div>

      <div className="landing__row">
        <span className="landing__row-label">1. Data</span>
        <div className="landing__tiles">
          <SourceTile
            kind="input"
            icon="🛰️"
            arrow="down"
            title="Model input data"
            desc="Driver/forcing grids (optional)"
            source={activeInput}
            onClick={onOpenSource}
          />
          <SourceTile
            kind="output"
            icon="📊"
            arrow="up"
            title="Model output data"
            desc="Ecosim/Ecospace results (required)"
            source={activeOutput}
            onClick={onOpenSource}
          />
        </div>
      </div>

      <div className="landing__row">
        <span className="landing__row-label">2. Explore</span>
        <div className="landing__tiles">
          <button className="landing__tile" onClick={() => onSelect("spatial")} disabled={!ready}>
            <span className="landing__icon" aria-hidden="true">🗺️</span>
            <span className="landing__tile-title">Spatial data</span>
            <span className="landing__tile-desc">Ecospace ASCII maps (.asc)</span>
          </button>
          <button className="landing__tile" onClick={() => onSelect("timeseries")} disabled={!ready}>
            <span className="landing__icon" aria-hidden="true">📈</span>
            <span className="landing__tile-title">Time series</span>
            <span className="landing__tile-desc">Ecosim CSV output &amp; drivers</span>
          </button>
          <button className="landing__tile" onClick={() => onSelect("montecarlo")} disabled={!ready}>
            <span className="landing__icon" aria-hidden="true">🎲</span>
            <span className="landing__tile-title">Monte Carlo</span>
            <span className="landing__tile-desc">Same scenario across multiple setups</span>
            <span className="badge badge--muted landing__tile-badge">In progress</span>
          </button>
        </div>
        {!ready && (
          <p className="muted landing__row-note">Set “Model output data” above to unlock these.</p>
        )}
      </div>
    </div>
  );
}
