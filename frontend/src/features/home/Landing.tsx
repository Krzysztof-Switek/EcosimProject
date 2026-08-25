type Module = "spatial" | "timeseries";

export function Landing({ onSelect }: { onSelect: (m: Module) => void }) {
  return (
    <div className="landing">
      <div className="landing__intro">
        <h1 className="landing__title">Ecosim Results Explorer</h1>
        <p className="landing__subtitle">Choose what you want to work with.</p>
      </div>
      <div className="landing__tiles">
        <button className="landing__tile" onClick={() => onSelect("spatial")}>
          <span className="landing__icon" aria-hidden="true">🗺️</span>
          <span className="landing__tile-title">Spatial data</span>
          <span className="landing__tile-desc">Ecospace ASCII maps (.asc)</span>
          <span className="badge badge--muted landing__tile-badge">In progress</span>
        </button>
        <button className="landing__tile" onClick={() => onSelect("timeseries")}>
          <span className="landing__icon" aria-hidden="true">📈</span>
          <span className="landing__tile-title">Time series</span>
          <span className="landing__tile-desc">Ecosim CSV output &amp; drivers</span>
        </button>
      </div>
    </div>
  );
}
