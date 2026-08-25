import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { DimItem, RasterEntry } from "../../api/types";
import { RasterMap, type RasterStats } from "./RasterMap";
import { RasterLegend } from "./RasterLegend";
import { PALETTE_OPTIONS, PALETTE_SWATCH, type PaletteId } from "./colorScale";

const AOI_STORAGE_KEY = "ecosim.aois.v2";

interface NamedAoi {
  id: string;
  name: string;
  geojson: GeoJSON.FeatureCollection;
}

interface StoredAois {
  aois: NamedAoi[];
  activeId: string | null;
}

function formatLabel(slug: string): string {
  const words = slug.split("_");
  return words.map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(" ");
}

function loadStoredAois(): StoredAois {
  try {
    const raw = localStorage.getItem(AOI_STORAGE_KEY);
    if (!raw) return { aois: [], activeId: null };
    const parsed = JSON.parse(raw) as Partial<StoredAois>;
    return { aois: parsed.aois ?? [], activeId: parsed.activeId ?? null };
  } catch {
    return { aois: [], activeId: null };
  }
}

let aoiIdSeq = 0;
function makeAoiId(): string {
  aoiIdSeq += 1;
  return `aoi_${Date.now()}_${aoiIdSeq}`;
}

/** "Area 1", "Area 2", ... skipping any name already taken. */
function nextAoiName(existing: NamedAoi[]): string {
  const taken = new Set(existing.map((a) => a.name));
  let n = existing.length + 1;
  while (taken.has(`Area ${n}`)) n++;
  return `Area ${n}`;
}

/** Parse an uploaded area-of-interest file: GeoJSON directly, or a shapefile (.zip/.shp) via shpjs. */
async function parseAoiFile(file: File): Promise<GeoJSON.FeatureCollection> {
  const name = file.name.toLowerCase();
  if (name.endsWith(".geojson") || name.endsWith(".json")) {
    const parsed = JSON.parse(await file.text());
    return parsed.type === "FeatureCollection" ? parsed : { type: "FeatureCollection", features: [parsed] };
  }
  const shp = (await import("shpjs")).default;
  const result = await shp(await file.arrayBuffer());
  return Array.isArray(result) ? result[0] : result;
}

/** Sort entity names by their dictionary id order, falling back to alphabetical. */
function sortByDict(names: string[], dict: DimItem[]): string[] {
  const order = new Map(dict.map((d) => [d.name, d.id]));
  return [...names].sort((a, b) => {
    const oa = order.get(a);
    const ob = order.get(b);
    if (oa != null && ob != null) return oa - ob;
    return a.localeCompare(b);
  });
}

export function SpatialView({ groups, fleets }: { groups: DimItem[]; fleets: DimItem[] }) {
  const layers = useAsync(() => api.spatialLayers(), []);

  const [scenario, setScenario] = useState<string | null>(null);
  const [variable, setVariable] = useState<string | null>(null);
  const [entity, setEntity] = useState<string | null>(null);
  const [year, setYear] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [stats, setStats] = useState<(RasterStats & { dataMin: number; dataMax: number }) | null>(null);
  const [aois, setAois] = useState<NamedAoi[]>(() => loadStoredAois().aois);
  const [activeAoiId, setActiveAoiId] = useState<string | null>(() => loadStoredAois().activeId);
  const [aoiError, setAoiError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const activeAoi = useMemo(
    () => aois.find((a) => a.id === activeAoiId)?.geojson ?? null,
    [aois, activeAoiId],
  );

  // Color scale: palette/invert are sticky display preferences; the domain
  // (auto vs. a manually fixed min/max) resets whenever the data series
  // changes, since a range fixed for one variable rarely makes sense for another.
  const [palette, setPalette] = useState<PaletteId>("blue");
  const [invert, setInvert] = useState(false);
  const [domainMode, setDomainMode] = useState<"auto" | "manual">("auto");
  const [manualMin, setManualMin] = useState("");
  const [manualMax, setManualMax] = useState("");
  // Memoized: a fresh object literal here every render (this component
  // re-renders often, e.g. on every autoplay tick) would make RasterMap's
  // effect see a "changed" prop each time and re-run forever.
  const domainOverride: RasterStats | null = useMemo(() => {
    const min = Number(manualMin);
    const max = Number(manualMax);
    if (domainMode !== "manual" || manualMin === "" || manualMax === "" || Number.isNaN(min) || Number.isNaN(max)) {
      return null;
    }
    return { min, max };
  }, [domainMode, manualMin, manualMax]);

  useEffect(() => {
    try {
      localStorage.setItem(AOI_STORAGE_KEY, JSON.stringify({ aois, activeId: activeAoiId }));
    } catch {
      // best-effort persistence only
    }
  }, [aois, activeAoiId]);

  // A shape drawn on the map is a new saved area, not an edit of whichever
  // was active -- add it to the library and switch to it.
  const handleAoiDrawn = (geojson: GeoJSON.FeatureCollection) => {
    const id = makeAoiId();
    setAois((prev) => [...prev, { id, name: nextAoiName(prev), geojson }]);
    setActiveAoiId(id);
  };

  // Map-toolbar delete only unclips the view; the saved entry stays in the
  // library (removed explicitly from the list below, if wanted).
  const handleAoiCleared = () => setActiveAoiId(null);

  const handleAoiUpload = async (file: File) => {
    setAoiError(null);
    try {
      const geojson = await parseAoiFile(file);
      const id = makeAoiId();
      const baseName = file.name.replace(/\.(geojson|json|zip|shp)$/i, "") || "Uploaded area";
      setAois((prev) => [
        ...prev,
        { id, name: prev.some((a) => a.name === baseName) ? nextAoiName(prev) : baseName, geojson },
      ]);
      setActiveAoiId(id);
    } catch (err) {
      setAoiError(`Could not read ${file.name}: ${(err as Error).message}`);
    }
  };

  const renameAoi = (id: string, name: string) =>
    setAois((prev) => prev.map((a) => (a.id === id ? { ...a, name } : a)));

  const deleteAoi = (id: string) => {
    setAois((prev) => prev.filter((a) => a.id !== id));
    setActiveAoiId((cur) => (cur === id ? null : cur));
  };

  const scenarioGroups = useMemo(() => {
    const models = new Map<string, { model_name: string; scenarios: Set<string> }>();
    const drivers = new Set<string>();
    for (const l of layers.data ?? []) {
      if (l.domain === "output" && l.model) {
        const m = models.get(l.model) ?? { model_name: l.model_name ?? l.model, scenarios: new Set() };
        m.scenarios.add(l.scenario);
        models.set(l.model, m);
      } else if (l.domain === "input") {
        drivers.add(l.scenario);
      }
    }
    return { models, drivers: [...drivers].sort() };
  }, [layers.data]);

  const variablesForScenario = useMemo(
    () => (layers.data ?? []).filter((l) => l.scenario === scenario),
    [layers.data, scenario],
  );
  const activeLayer = useMemo(
    () => variablesForScenario.find((l) => l.variable === variable) ?? null,
    [variablesForScenario, variable],
  );
  const hasEntity = !!activeLayer && (activeLayer.n_groups > 0 || activeLayer.n_fleets > 0);
  const entityKind: "group" | "fleet" | null = !activeLayer
    ? null
    : activeLayer.n_groups > 0
      ? "group"
      : activeLayer.n_fleets > 0
        ? "fleet"
        : null;

  const rasters = useAsync(
    () => (scenario && variable ? api.spatialRasters({ scenario, variable }) : Promise.resolve<RasterEntry[]>([])),
    [scenario, variable],
  );

  const entityNames = useMemo(() => {
    if (!hasEntity) return [];
    const names = new Set<string>();
    for (const r of rasters.data ?? []) {
      const n = entityKind === "group" ? r.group_name : r.fleet_name;
      if (n) names.add(n);
    }
    return sortByDict([...names], entityKind === "group" ? groups : fleets);
  }, [rasters.data, hasEntity, entityKind, groups, fleets]);

  // Reset downstream selections when an upstream one changes.
  useEffect(() => {
    setVariable(null);
    setEntity(null);
    setYear(null);
    setPlaying(false);
  }, [scenario]);

  useEffect(() => {
    setEntity(null);
    setYear(null);
    setPlaying(false);
    setDomainMode("auto");
    setManualMin("");
    setManualMax("");
  }, [variable]);

  const enableManualDomain = () => {
    if (stats) {
      setManualMin(String(stats.dataMin));
      setManualMax(String(stats.dataMax));
    }
    setDomainMode("manual");
  };

  // Once the raster list for (scenario, variable) is known, default to
  // something viewable: first entity (if any) and the most recent year.
  useEffect(() => {
    if (!activeLayer) return;
    if (hasEntity && entity == null && entityNames.length > 0) setEntity(entityNames[0]);
    if (year == null) setYear(activeLayer.year_max);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeLayer, entityNames]);

  // Autoplay through the year range.
  useEffect(() => {
    if (!playing || !activeLayer) return;
    const id = setInterval(() => {
      setYear((y) => {
        if (y == null) return activeLayer.year_min;
        return y >= activeLayer.year_max ? activeLayer.year_min : y + 1;
      });
    }, 700);
    return () => clearInterval(id);
  }, [playing, activeLayer]);

  const findRasterForYear = (y: number) =>
    (rasters.data ?? []).find(
      (r) =>
        r.year === y &&
        (!hasEntity || (entityKind === "group" ? r.group_name === entity : r.fleet_name === entity)),
    ) ?? null;

  const activeRaster = useMemo(
    () => (scenario && variable && year != null ? findRasterForYear(year) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rasters.data, scenario, variable, year, hasEntity, entityKind, entity],
  );
  const rasterUrl = activeRaster ? api.spatialRasterUrl(activeRaster.id) : null;

  // Fetch+parse the next year in the background while the current one is
  // showing, so autoplay/scrubbing forward rarely has to wait on a fresh
  // server-side conversion -- see RasterMap's cache.
  const nextRaster = useMemo(() => {
    if (!scenario || !variable || year == null || !activeLayer) return null;
    const nextYear = year >= activeLayer.year_max ? activeLayer.year_min : year + 1;
    return findRasterForYear(nextYear);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rasters.data, scenario, variable, year, activeLayer, hasEntity, entityKind, entity]);
  const prefetchUrl = nextRaster ? api.spatialRasterUrl(nextRaster.id) : null;

  const loading = layers.loading;
  const error = layers.error;

  return (
    <div className="analysis">
      <aside className="analysis__controls">
        {error && <div className="error">Cannot reach API: {error}</div>}
        {loading && <div className="muted">Loading spatial catalog…</div>}

        <div className="step">
          <div className="step__head step__head--static">
            <span className="step__n">1</span>
            <span className="step__title">Scenario</span>
          </div>
          <div className="step__body picker">
            {[...scenarioGroups.models.entries()].map(([modelId, m]) => (
              <div className="picker__group" key={modelId}>
                <div className="picker__group-head">
                  <span className="picker__group-title">{m.model_name}</span>
                </div>
                {[...m.scenarios].sort().map((s) => (
                  <button
                    key={s}
                    className={`catalog__item picker__item--indent${scenario === s ? " is-active" : ""}`}
                    onClick={() => setScenario(s)}
                  >
                    <span className="catalog__item-label">{s}</span>
                  </button>
                ))}
              </div>
            ))}
            {scenarioGroups.drivers.length > 0 && (
              <div className="picker__group">
                <div className="picker__group-head">
                  <span className="picker__group-title">Drivers (inputs)</span>
                </div>
                {scenarioGroups.drivers.map((s) => (
                  <button
                    key={s}
                    className={`catalog__item picker__item--indent${scenario === s ? " is-active" : ""}`}
                    onClick={() => setScenario(s)}
                  >
                    <span className="catalog__item-label">{s.toUpperCase()}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="step">
          <div className="step__head step__head--static">
            <span className="step__n">2</span>
            <span className="step__title">Variable</span>
          </div>
          <div className="step__body picker">
            {!scenario && <span className="muted">select a scenario first</span>}
            {variablesForScenario.map((l) => (
              <button
                key={l.variable}
                className={`catalog__item${variable === l.variable ? " is-active" : ""}`}
                onClick={() => setVariable(l.variable)}
              >
                <span className="catalog__item-label">{formatLabel(l.variable)}</span>
              </button>
            ))}
          </div>
        </div>

        {hasEntity && (
          <div className="step">
            <div className="step__head step__head--static">
              <span className="step__n">3</span>
              <span className="step__title">{entityKind === "fleet" ? "Fleet" : "Group"}</span>
            </div>
            <div className="step__body picker">
              {entityNames.map((n) => (
                <button
                  key={n}
                  className={`catalog__item${entity === n ? " is-active" : ""}`}
                  onClick={() => setEntity(n)}
                >
                  <span className="catalog__item-label">{n}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {activeLayer && year != null && (
          <div className="step">
            <div className="step__head step__head--static">
              <span className="step__n">{hasEntity ? 4 : 3}</span>
              <span className="step__title">Year</span>
              <span className="step__hint muted">{year}</span>
            </div>
            <div className="step__body">
              <div className="yearctl">
                <button className="btn btn--ghost" onClick={() => setPlaying((p) => !p)}>
                  {playing ? "⏸" : "▶"}
                </button>
                <input
                  type="range"
                  min={activeLayer.year_min}
                  max={activeLayer.year_max}
                  value={year}
                  onChange={(e) => {
                    setPlaying(false);
                    setYear(Number(e.target.value));
                  }}
                />
              </div>
              <div className="yearctl__range muted">
                {activeLayer.year_min} – {activeLayer.year_max}
              </div>
            </div>
          </div>
        )}

        <div className="step">
          <div className="step__head step__head--static">
            <span className="step__title">Color scale</span>
          </div>
          <div className="step__body colorctl">
            <div className="colorctl__row">
              {PALETTE_OPTIONS.map((p) => (
                <button
                  key={p.id}
                  className={`swatchbtn${palette === p.id ? " is-active" : ""}`}
                  style={{ background: PALETTE_SWATCH[p.id] }}
                  title={p.label}
                  onClick={() => setPalette(p.id)}
                >
                  <span className="sr-only">{p.label}</span>
                </button>
              ))}
              <label className="check colorctl__invert">
                <input type="checkbox" checked={invert} onChange={(e) => setInvert(e.target.checked)} />
                Invert
              </label>
            </div>
            <div className="colorctl__domain">
              <label className="check">
                <input
                  type="radio"
                  name="domain-mode"
                  checked={domainMode === "auto"}
                  onChange={() => setDomainMode("auto")}
                />
                Auto (this map's range)
              </label>
              <label className="check">
                <input type="radio" name="domain-mode" checked={domainMode === "manual"} onChange={enableManualDomain} />
                Fixed range
              </label>
              {domainMode === "manual" && (
                <div className="colorctl__minmax">
                  <input
                    type="number"
                    value={manualMin}
                    onChange={(e) => setManualMin(e.target.value)}
                    placeholder="min"
                  />
                  <span className="muted">–</span>
                  <input
                    type="number"
                    value={manualMax}
                    onChange={(e) => setManualMax(e.target.value)}
                    placeholder="max"
                  />
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="step">
          <div className="step__head step__head--static">
            <span className="step__title">Area of interest</span>
          </div>
          <div className="step__body aoictl">
            <p className="muted aoictl__hint">
              Draw a polygon on the map (top-right tool — click each corner, then click the
              first point again to close it) or upload one. Each area is saved by name so you
              can switch between several, or come back to one later.
            </p>
            <div className="aoictl__row">
              <button className="btn btn--ghost" onClick={() => fileInputRef.current?.click()}>
                Upload file
              </button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".geojson,.json,.zip,.shp"
              className="aoictl__file-input"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleAoiUpload(file);
                e.target.value = "";
              }}
            />
            {aoiError && <div className="error">{aoiError}</div>}

            <div className="aoilist">
              <label className="aoilist__item">
                <input
                  type="radio"
                  name="active-aoi"
                  checked={activeAoiId === null}
                  onChange={() => setActiveAoiId(null)}
                />
                <span className="muted">None (full map)</span>
              </label>
              {aois.map((a) => (
                <div className="aoilist__item" key={a.id}>
                  <input
                    type="radio"
                    name="active-aoi"
                    checked={activeAoiId === a.id}
                    onChange={() => setActiveAoiId(a.id)}
                  />
                  <input
                    className="aoilist__name"
                    value={a.name}
                    onChange={(e) => renameAoi(a.id, e.target.value)}
                  />
                  <button
                    className="linkbtn aoilist__delete"
                    onClick={() => deleteAoi(a.id)}
                    title={`Delete "${a.name}"`}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      </aside>

      <main className="analysis__main spatialmain">
        {!scenario && (
          <div className="muted pad">Pick a scenario, then a variable, to see a map.</div>
        )}
        {scenario && variable && (
          <>
            <RasterMap
              rasterUrl={rasterUrl}
              prefetchUrl={prefetchUrl}
              onStats={setStats}
              activeAoi={activeAoi}
              onAoiDrawn={handleAoiDrawn}
              onAoiCleared={handleAoiCleared}
              palette={palette}
              invert={invert}
              domainOverride={domainOverride}
            />
            <RasterLegend stats={stats} unitLabel={formatLabel(variable)} palette={palette} invert={invert} />
          </>
        )}
      </main>
    </div>
  );
}
