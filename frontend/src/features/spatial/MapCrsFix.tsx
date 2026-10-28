import { useState } from "react";
import { api } from "../../api/client";
import type { MapCrsMismatch } from "../../api/types";

const fmtLon = (v: number) => `${Math.abs(v).toFixed(1)}°${v < 0 ? "W" : "E"}`;
const fmtLat = (v: number) => `${Math.abs(v).toFixed(1)}°${v < 0 ? "S" : "N"}`;

/**
 * Shown over the map when a raster's coordinates can't be in the CRS EwE
 * declared (e.g. metres declared as WGS 84). The data never says which CRS is
 * right, so the user picks one: each candidate shows where it would put the
 * map, which is usually enough to tell (the model's sea area vs. somewhere
 * else). Saved per data source; every map of that source is then reprojected.
 */
export function MapCrsFix({ info, onApplied }: { info: MapCrsMismatch; onApplied: () => void }) {
  const [choice, setChoice] = useState<string>("");
  const [custom, setCustom] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = choice === "custom" ? custom.trim() : choice;
  const [w, s, e, n] = info.bounds;

  const apply = async () => {
    if (!info.source_id || !selected) return;
    setSaving(true);
    setError(null);
    try {
      await api.setMapCrs(info.source_id, selected);
      onApplied();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="crsfix">
      <div className="crsfix__title">This map's coordinate system needs to be set</div>
      <p className="crsfix__text">
        The map's coordinates (x {w.toLocaleString()} to {e.toLocaleString()}, y {s.toLocaleString()} to{" "}
        {n.toLocaleString()}) can't be degrees, yet EwE declares <strong>{info.crs}</strong>, which is in
        degrees. The map is most likely on a metric grid, so it can't be placed correctly as is. The files don't say which coordinate system is
        right. Pick the one the model was built on. Each option shows where it would put the map.
        {info.source_name && (
          <>
            {" "}The choice is saved for the data source <strong>{info.source_name}</strong>.
          </>
        )}
      </p>
      <div className="crsfix__list">
        {info.candidates.map((c) => (
          <label key={c.crs} className={`crsfix__item ${c.extent ? "" : "is-disabled"}`}>
            <input
              type="radio"
              name="crs"
              value={c.crs}
              disabled={!c.extent}
              checked={choice === c.crs}
              onChange={() => setChoice(c.crs)}
            />
            <span className="crsfix__code">{c.crs}</span>
            <span className="crsfix__name">{c.name}</span>
            <span className="crsfix__extent muted">
              {c.extent
                ? `${fmtLon(c.extent[0])} ${fmtLat(c.extent[1])} – ${fmtLon(c.extent[2])} ${fmtLat(c.extent[3])}`
                : "doesn't fit on the globe"}
            </span>
          </label>
        ))}
        <label className="crsfix__item">
          <input type="radio" name="crs" checked={choice === "custom"} onChange={() => setChoice("custom")} />
          <span className="crsfix__code">Other</span>
          <input
            className="crsfix__custom"
            placeholder="e.g. EPSG:25834"
            value={custom}
            onFocus={() => setChoice("custom")}
            onChange={(ev) => setCustom(ev.target.value)}
          />
        </label>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="crsfix__actions">
        <button className="btn" disabled={!selected || saving || !info.source_id} onClick={apply}>
          {saving ? "Applying…" : "Apply"}
        </button>
      </div>
    </div>
  );
}
