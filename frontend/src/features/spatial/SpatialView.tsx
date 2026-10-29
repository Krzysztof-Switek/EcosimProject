import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { DimItem, RasterEntry } from "../../api/types";
import { Step } from "../../components/Step";
import { MapViewSync, RasterMap, type RasterStats } from "./RasterMap";
import { RasterLegend } from "./RasterLegend";
import { ExportPanel } from "./ExportPanel";
import { PALETTE_OPTIONS, PALETTE_SWATCH, type PaletteId } from "./colorScale";

const AOI_STORAGE_KEY = "ecosim.aois.v2";

interface NamedAoi {
  id: string;
  name: string;
  geojson: GeoJSON.FeatureCollection;
}

interface StoredAois {
  aois: NamedAoi[];
  selectedAoiIds: string[];
}

function formatLabel(slug: string): string {
  const words = slug.split("_");
  return words.map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(" ");
}

function loadStoredAois(): StoredAois {
  try {
    const raw = localStorage.getItem(AOI_STORAGE_KEY);
    if (!raw) return { aois: [], selectedAoiIds: [] };
    // `activeId` is the old (pre-multi-select) single-selection field --
    // migrate it into the new array in place so existing saved areas aren't
    // dropped just because the selection model changed.
    const parsed = JSON.parse(raw) as Partial<StoredAois> & { activeId?: string | null };
    const aois = parsed.aois ?? [];
    const selectedAoiIds = parsed.selectedAoiIds ?? (parsed.activeId ? [parsed.activeId] : []);
    return { aois, selectedAoiIds };
  } catch {
    return { aois: [], selectedAoiIds: [] };
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

type MapStats = RasterStats & { dataMin: number; dataMax: number };

/**
 * What each variable remembers for itself: its groups/fleets, year range and
 * colour scale. Switching between the checked variables (the pills above the
 * map) brings back that variable's own choices, and the download applies each
 * variable's own -- Biomass of two groups on a fixed scale next to Catch of
 * another group over a narrower range, say.
 */
export interface VariableSettings {
  /** Checked groups/fleets; null = not chosen yet (the first one gets checked). */
  entities: string[] | null;
  /** Custom sub-range within the available years; null = from/to the first/last year. */
  yearMin: number | null;
  yearMax: number | null;
  palette: PaletteId;
  invert: boolean;
  domainMode: "auto" | "manual";
  manualMin: string;
  manualMax: string;
}

const DEFAULT_VARIABLE_SETTINGS: VariableSettings = {
  entities: null,
  yearMin: null,
  yearMax: null,
  palette: "blue",
  invert: false,
  domainMode: "auto",
  manualMin: "",
  manualMax: "",
};

/** The fixed colour-scale range, or null for auto (each map scaled to its own range). */
export function domainOf(settings: VariableSettings): RasterStats | null {
  const min = Number(settings.manualMin);
  const max = Number(settings.manualMax);
  if (
    settings.domainMode !== "manual" || settings.manualMin === "" || settings.manualMax === ""
    || Number.isNaN(min) || Number.isNaN(max)
  ) {
    return null;
  }
  return { min, max };
}

export function SpatialView({ groups, fleets }: { groups: DimItem[]; fleets: DimItem[] }) {
  const layers = useAsync(() => api.spatialLayers(), []);

  // Which numbered steps are collapsed -- starts with everything collapsed
  // (a step you open stays open until you close it again; nothing else auto-
  // collapses it), matching the timeseries Sidebar's Step behavior this view
  // already mirrors, but defaulting closed here to keep the sidebar short.
  const [collapsedSteps, setCollapsedSteps] = useState<Set<string>>(
    () => new Set(["scenario", "variable", "entity", "year", "color", "aoi", "export"]),
  );
  const isStepOpen = (id: string) => !collapsedSteps.has(id);
  const toggleStep = (id: string) =>
    setCollapsedSteps((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const [scenario, setScenario] = useState<string | null>(null);
  const [variable, setVariable] = useState<string | null>(null);
  // Variables marked with a checkbox -- independent of which one is actually
  // shown on the map (`variable` above). Multiple can't be displayed at once
  // (different fields/units), but the marked set is what a later export or
  // R-analysis step would act on -- same "select now, use later" pattern as
  // the area-of-interest library.
  const [selectedVariables, setSelectedVariables] = useState<Set<string>>(new Set());
  // Groups/fleets (step 3), year range (step 4) and colour scale (step 5),
  // separately for each variable -- see VariableSettings.
  const [settingsByVariable, setSettingsByVariable] = useState<Record<string, VariableSettings>>({});
  const settings = (variable && settingsByVariable[variable]) || DEFAULT_VARIABLE_SETTINGS;
  const updateSettings = (patch: Partial<VariableSettings>) => {
    if (!variable) return;
    setSettingsByVariable((prev) => ({
      ...prev,
      [variable]: { ...(prev[variable] ?? DEFAULT_VARIABLE_SETTINGS), ...patch },
    }));
  };
  // The year on screen is shared: switching variables shows the same year,
  // kept inside the newly shown variable's range.
  const [year, setYear] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  // Per map (keyed like the maps themselves, see mapPanels).
  const [statsByMap, setStatsByMap] = useState<Record<string, MapStats>>({});
  // Bumped once a source's CRS is fixed, so every map on screen re-fetches.
  const [crsReloadToken, setCrsReloadToken] = useState(0);
  // All maps on screen pan and zoom together.
  const viewSync = useMemo(() => new MapViewSync(), []);
  const [aois, setAois] = useState<NamedAoi[]>(() => loadStoredAois().aois);
  const [selectedAoiIds, setSelectedAoiIds] = useState<string[]>(() => loadStoredAois().selectedAoiIds);
  const [aoiError, setAoiError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  // Every currently-checked area, in list order -- shown (outlined) on the
  // map and clipped to as a union; memoized so RasterMap's effects only
  // re-fire when the actual selection changes, not on every render.
  const selectedAois = useMemo(
    () => aois.filter((a) => selectedAoiIds.includes(a.id)),
    [aois, selectedAoiIds],
  );

  const { palette, invert, domainMode, manualMin, manualMax } = settings;
  // Memoized: a fresh object literal here every render (this component
  // re-renders often, e.g. on every autoplay tick) would make RasterMap's
  // effect see a "changed" prop each time and re-run forever.
  const domainOverride: RasterStats | null = useMemo(
    () => domainOf(settings),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [domainMode, manualMin, manualMax],
  );

  useEffect(() => {
    try {
      localStorage.setItem(AOI_STORAGE_KEY, JSON.stringify({ aois, selectedAoiIds }));
    } catch {
      // best-effort persistence only
    }
  }, [aois, selectedAoiIds]);

  // A shape drawn on the map is a new saved area -- add it to the library
  // and select it (on top of whatever else is already selected).
  const handleAoiDrawn = (geojson: GeoJSON.FeatureCollection) => {
    const id = makeAoiId();
    setAois((prev) => [...prev, { id, name: nextAoiName(prev), geojson }]);
    setSelectedAoiIds((prev) => [...prev, id]);
  };

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
      setSelectedAoiIds((prev) => [...prev, id]);
    } catch (err) {
      setAoiError(`Could not read ${file.name}: ${(err as Error).message}`);
    }
  };

  const toggleAoiSelected = (id: string) =>
    setSelectedAoiIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const renameAoi = (id: string, name: string) =>
    setAois((prev) => prev.map((a) => (a.id === id ? { ...a, name } : a)));

  const deleteAoi = (id: string) => {
    setAois((prev) => prev.filter((a) => a.id !== id));
    setSelectedAoiIds((prev) => prev.filter((x) => x !== id));
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

  // Bumped by the "Retry" shown when the variable's map list failed to load.
  const [rastersRetry, setRastersRetry] = useState(0);
  const rasters = useAsync(
    () => (scenario && variable ? api.spatialRasters({ scenario, variable }) : Promise.resolve<RasterEntry[]>([])),
    [scenario, variable, rastersRetry],
  );

  const entityNames = useMemo(() => {
    if (!hasEntity) return [];
    const names = new Set<string>();
    for (const r of rasters.data ?? []) {
      // Right after switching variables rasters.data still holds the previous
      // variable's list -- its names would be taken for this one's (and the
      // first-time pick below would check a group this variable doesn't have).
      if (r.variable !== variable || r.scenario !== scenario) continue;
      const n = entityKind === "group" ? r.group_name : r.fleet_name;
      if (n) names.add(n);
    }
    return sortByDict([...names], entityKind === "group" ? groups : fleets);
  }, [rasters.data, variable, scenario, hasEntity, entityKind, groups, fleets]);

  const selectedEntities = useMemo(() => new Set(settings.entities ?? []), [settings.entities]);
  // In the order of the list, and only names this variable's maps really have.
  const visibleSelectedEntities = useMemo(
    () => entityNames.filter((n) => selectedEntities.has(n)),
    [entityNames, selectedEntities],
  );

  // Reset downstream selections when an upstream one changes.
  useEffect(() => {
    setVariable(null);
    setSelectedVariables(new Set());
    setSettingsByVariable({});
    setYear(null);
    setPlaying(false);
  }, [scenario]);

  // Checking a variable also shows it on the map -- checking it and seeing
  // nothing happen read as broken. Unchecking the one on the map moves the map
  // to another still-checked variable (or clears it if none is left).
  const toggleVariableSelected = (v: string) => {
    const next = new Set(selectedVariables);
    if (next.has(v)) {
      next.delete(v);
      if (variable === v) setVariable(next.values().next().value ?? null);
    } else {
      next.add(v);
      setVariable(v);
    }
    setSelectedVariables(next);
  };

  // Clicking a variable's name shows it on the map; it's implicitly marked
  // (checked) too, since viewing something usually means you care about it --
  // the checkbox stays there to mark others (or un-mark this one) separately.
  const focusVariable = (v: string) => {
    setVariable(v);
    setSelectedVariables((prev) => (prev.has(v) ? prev : new Set(prev).add(v)));
  };

  const toggleEntitySelected = (n: string) => {
    const next = new Set(selectedEntities);
    next.has(n) ? next.delete(n) : next.add(n);
    updateSettings({ entities: [...next] });
  };

  // Switching variables stops autoplay; everything chosen for a variable stays
  // with it (VariableSettings).
  useEffect(() => {
    setPlaying(false);
  }, [variable]);

  // Prefilled with the range across every map on screen, so one fixed scale
  // makes the maps directly comparable.
  const enableManualDomain = () => {
    const all = Object.values(statsByMap);
    updateSettings({
      domainMode: "manual",
      ...(all.length > 0
        ? {
            manualMin: String(Math.min(...all.map((s) => s.dataMin))),
            manualMax: String(Math.max(...all.map((s) => s.dataMax))),
          }
        : {}),
    });
  };

  // A variable shown for the first time starts with its first group/fleet
  // checked, so picking a variable always shows a map. Only the first time:
  // unchecking every group afterwards leaves none. Also seeds the year on the
  // very first pick.
  useEffect(() => {
    if (!activeLayer) return;
    if (hasEntity && entityNames.length > 0 && settings.entities == null) {
      updateSettings({ entities: [entityNames[0]] });
    }
    if (year == null) setYear(activeLayer.year_max);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeLayer, entityNames]);

  // Effective slider/autoplay bounds: the full available range, narrowed to
  // whatever the user typed into the range inputs (if anything).
  const yearLo = settings.yearMin ?? activeLayer?.year_min ?? 0;
  const yearHi = settings.yearMax ?? activeLayer?.year_max ?? 0;

  // Each checked variable with its own settings -- what the download exports.
  const exportItems = [...selectedVariables].flatMap((v) => {
    const layer = variablesForScenario.find((l) => l.variable === v);
    if (!layer) return [];
    const vs = settingsByVariable[v] ?? DEFAULT_VARIABLE_SETTINGS;
    return [{
      variable: v,
      entities: vs.entities ?? [],
      yearFrom: vs.yearMin ?? layer.year_min,
      yearTo: vs.yearMax ?? layer.year_max,
      palette: vs.palette,
      invert: vs.invert,
      domainOverride: domainOf(vs),
    }];
  });

  // Which variable steps 3-5 apply to, as a chip in their headers once several are checked.
  const forVariable = selectedVariables.size > 1 && variable ? formatLabel(variable) : undefined;

  // Keep the current year inside the (possibly just-narrowed) range.
  useEffect(() => {
    if (!activeLayer || year == null) return;
    if (year < yearLo) setYear(yearLo);
    else if (year > yearHi) setYear(yearHi);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [yearLo, yearHi]);

  // Autoplay through the (possibly narrowed) year range.
  useEffect(() => {
    if (!playing || !activeLayer) return;
    const id = setInterval(() => {
      setYear((y) => {
        if (y == null) return yearLo;
        return y >= yearHi ? yearLo : y + 1;
      });
    }, 700);
    return () => clearInterval(id);
  }, [playing, activeLayer, yearLo, yearHi]);

  // One map per checked group/fleet (a single map for a variable without
  // them), each with the raster for the current year, plus the next year's to
  // fetch+parse in the background so autoplay/scrubbing forward rarely waits
  // on a fresh server-side conversion -- see RasterMap's cache.
  const mapPanels = useMemo(() => {
    if (!scenario || !variable || year == null || !activeLayer) return [];
    const nextYear = year >= activeLayer.year_max ? activeLayer.year_min : year + 1;
    const findRaster = (y: number, ent: string | null) =>
      (rasters.data ?? []).find(
        (r) =>
          r.year === y &&
          r.variable === variable && // not the previous variable's list, still there right after a switch
          (ent == null || (entityKind === "group" ? r.group_name === ent : r.fleet_name === ent)),
      ) ?? null;
    return (hasEntity ? visibleSelectedEntities : [null]).map((ent) => {
      const current = findRaster(year, ent);
      const next = findRaster(nextYear, ent);
      return {
        key: ent ?? "",
        title: ent,
        rasterUrl: current ? api.spatialRasterUrl(current.id) : null,
        prefetchUrl: next ? api.spatialRasterUrl(next.id) : null,
      };
    });
  }, [rasters.data, scenario, variable, year, activeLayer, hasEntity, entityKind, visibleSelectedEntities]);

  // Stable per-map stats callbacks: RasterMap reports stats from an effect,
  // and a new function every render must not look like a changed prop.
  const statsSetters = useRef(new Map<string, (s: MapStats | null) => void>());
  const statsSetterFor = (key: string) => {
    let fn = statsSetters.current.get(key);
    if (!fn) {
      fn = (s) =>
        setStatsByMap((prev) => {
          const next = { ...prev };
          if (s) next[key] = s;
          else delete next[key];
          return next;
        });
      statsSetters.current.set(key, fn);
    }
    return fn;
  };
  // Drop stats of maps no longer on screen (they'd skew the fixed-range prefill).
  useEffect(() => {
    const keys = new Set(mapPanels.map((p) => p.key));
    setStatsByMap((prev) => {
      const stale = Object.keys(prev).filter((k) => !keys.has(k));
      if (stale.length === 0) return prev;
      const next = { ...prev };
      for (const k of stale) delete next[k];
      return next;
    });
  }, [mapPanels]);

  const loading = layers.loading;
  const error = layers.error;

  return (
    <div className="analysis">
      <aside className="analysis__controls">
        {error && <div className="error">Cannot reach API: {error}</div>}
        {loading && <div className="muted">Loading spatial catalog…</div>}

        <Step
          n={1}
          title="Scenario"
          hint={scenario ?? undefined}
          open={isStepOpen("scenario")}
          onToggle={() => toggleStep("scenario")}
        >
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
        </Step>

        <Step
          n={2}
          title="Variable"
          hint={selectedVariables.size > 0 ? `${selectedVariables.size} selected` : undefined}
          open={isStepOpen("variable")}
          onToggle={() => toggleStep("variable")}
        >
          {!scenario && <span className="muted">select a scenario first</span>}
          {variablesForScenario.map((l) => (
            <div
              key={l.variable}
              className={`catalog__item${variable === l.variable ? " is-shown" : selectedVariables.has(l.variable) ? " is-marked" : ""}`}
            >
              <input
                type="checkbox"
                className="catalog__check"
                checked={selectedVariables.has(l.variable)}
                onChange={() => toggleVariableSelected(l.variable)}
              />
              <span
                className="catalog__item-label catalog__item-label--btn"
                onClick={() => focusVariable(l.variable)}
                title="Show this variable on the map"
              >
                {formatLabel(l.variable)}
              </span>
              {variable === l.variable && <span className="catalog__onmap">on map</span>}
            </div>
          ))}
        </Step>

        {hasEntity && (
          <Step
            n={3}
            title={entityKind === "fleet" ? "Fleet" : "Group"}
            tag={forVariable}
            hint={
              visibleSelectedEntities.length === 1
                ? "1 map"
                : visibleSelectedEntities.length > 1
                  ? `${visibleSelectedEntities.length} maps`
                  : undefined
            }
            open={isStepOpen("entity")}
            onToggle={() => toggleStep("entity")}
          >
            {entityNames.map((n) => (
              <div key={n} className={`catalog__item${selectedEntities.has(n) ? " is-marked" : ""}`}>
                <input
                  type="checkbox"
                  className="catalog__check"
                  checked={selectedEntities.has(n)}
                  onChange={() => toggleEntitySelected(n)}
                />
                <span
                  className="catalog__item-label catalog__item-label--btn"
                  onClick={() => toggleEntitySelected(n)}
                  title={`Show or hide a map of this ${entityKind ?? "entity"}`}
                >
                  {n}
                </span>
              </div>
            ))}
          </Step>
        )}

        {activeLayer && year != null && (
          <Step
            n={hasEntity ? 4 : 3}
            title="Year"
            tag={forVariable}
            hint={String(year)}
            open={isStepOpen("year")}
            onToggle={() => toggleStep("year")}
            bodyClassName=""
          >
              <div className="yearctl">
                <button className="btn btn--ghost" onClick={() => setPlaying((p) => !p)}>
                  {playing ? "⏸" : "▶"}
                </button>
                <input
                  type="range"
                  min={yearLo}
                  max={yearHi}
                  value={year}
                  onChange={(e) => {
                    setPlaying(false);
                    setYear(Number(e.target.value));
                  }}
                />
              </div>
              <div className="yearctl__range">
                <span className="muted">Range</span>
                <input
                  type="number"
                  className="yearctl__rangeinput"
                  min={activeLayer.year_min}
                  max={yearHi}
                  value={yearLo}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    if (Number.isNaN(v)) return;
                    updateSettings({ yearMin: Math.min(Math.max(v, activeLayer.year_min), yearHi) });
                  }}
                />
                <span className="muted">–</span>
                <input
                  type="number"
                  className="yearctl__rangeinput"
                  min={yearLo}
                  max={activeLayer.year_max}
                  value={yearHi}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    if (Number.isNaN(v)) return;
                    updateSettings({ yearMax: Math.max(Math.min(v, activeLayer.year_max), yearLo) });
                  }}
                />
                <span className="muted">
                  (available: {activeLayer.year_min}–{activeLayer.year_max})
                </span>
                {(settings.yearMin != null || settings.yearMax != null) && (
                  <button
                    className="linkbtn"
                    onClick={() => {
                      updateSettings({ yearMin: null, yearMax: null });
                    }}
                  >
                    Reset
                  </button>
                )}
              </div>
          </Step>
        )}

        <Step
          n={hasEntity ? 5 : 4}
          title="Color scale"
          tag={forVariable}
          hint={`${PALETTE_OPTIONS.find((p) => p.id === palette)?.label ?? palette}${invert ? " (inverted)" : ""}`}
          open={isStepOpen("color")}
          onToggle={() => toggleStep("color")}
          bodyClassName="colorctl"
        >
            <div className="colorctl__row">
              {PALETTE_OPTIONS.map((p) => (
                <button
                  key={p.id}
                  className={`swatchbtn${palette === p.id ? " is-active" : ""}`}
                  style={{ background: PALETTE_SWATCH[p.id] }}
                  title={p.label}
                  onClick={() => updateSettings({ palette: p.id })}
                >
                  <span className="sr-only">{p.label}</span>
                </button>
              ))}
              <label className="check colorctl__invert">
                <input type="checkbox" checked={invert} onChange={(e) => updateSettings({ invert: e.target.checked })} />
                Invert
              </label>
            </div>
            <div className="colorctl__domain">
              <label className="check">
                <input
                  type="radio"
                  name="domain-mode"
                  checked={domainMode === "auto"}
                  onChange={() => updateSettings({ domainMode: "auto" })}
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
                    onChange={(e) => updateSettings({ manualMin: e.target.value })}
                    placeholder="min"
                  />
                  <span className="muted">–</span>
                  <input
                    type="number"
                    value={manualMax}
                    onChange={(e) => updateSettings({ manualMax: e.target.value })}
                    placeholder="max"
                  />
                </div>
              )}
            </div>
        </Step>

        <Step
          n={hasEntity ? 6 : 5}
          title="Area of interest"
          hint={selectedAoiIds.length > 0 ? `${selectedAoiIds.length} selected` : undefined}
          open={isStepOpen("aoi")}
          onToggle={() => toggleStep("aoi")}
          bodyClassName="aoictl"
        >
            <div className="aoictl__row">
              <button className="btn btn--ghost" onClick={() => fileInputRef.current?.click()}>
                Upload file
              </button>
              <span
                className="infoicon"
                tabIndex={0}
                title="Draw a polygon on the map (top-right tool — click each corner, then click the first point again to close it) or upload one. Each area is saved by name; check any number of them to show and clip the map to their combined extent — the same selection is what a later export/analysis step would use."
              >
                ⓘ
              </span>
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
              {aois.length === 0 && <span className="muted">No saved areas yet.</span>}
              {aois.map((a) => (
                <div className="aoilist__item" key={a.id}>
                  <input
                    type="checkbox"
                    checked={selectedAoiIds.includes(a.id)}
                    onChange={() => toggleAoiSelected(a.id)}
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
              {selectedAoiIds.length > 0 && (
                <button className="linkbtn aoilist__clear" onClick={() => setSelectedAoiIds([])}>
                  Clear selection (show full map)
                </button>
              )}
            </div>
        </Step>

        {scenario && activeLayer && year != null && (
          <Step
            n={hasEntity ? 7 : 6}
            title="Download"
            hint={selectedAoiIds.length > 0 ? "per area" : "whole area"}
            open={isStepOpen("export")}
            onToggle={() => toggleStep("export")}
            bodyClassName=""
          >
            <ExportPanel
              scenario={scenario}
              model={activeLayer.model_name ?? activeLayer.model}
              items={exportItems}
              labelOf={formatLabel}
              areas={selectedAois}
            />
          </Step>
        )}
      </aside>

      <main className="analysis__main spatialmain">
        {!scenario && (
          <div className="muted pad">Pick a scenario, then a variable, to see a map.</div>
        )}
        {scenario && !variable && <div className="muted pad">Pick a variable (step 2) to see a map.</div>}
        {scenario && variable && (
          <>
            {/* What's on the map: one tab per checked variable (the shown one
                filled), or just its name when only one is checked. */}
            <div className="vartabs" role="tablist" aria-label="Variable shown on the map">
              <span className="vartabs__label">Showing</span>
              {(selectedVariables.size > 0 ? [...selectedVariables] : [variable]).map((v) => (
                <button
                  key={v}
                  role="tab"
                  aria-selected={variable === v}
                  className={`vartabs__tab${variable === v ? " is-active" : ""}`}
                  onClick={() => focusVariable(v)}
                >
                  {formatLabel(v)}
                </button>
              ))}
            </div>
            {rasters.error && (
              <div className="error pad">
                Could not load the maps of {formatLabel(variable)}: {rasters.error}{" "}
                <button className="linkbtn" onClick={() => setRastersRetry((t) => t + 1)}>
                  Retry
                </button>
              </div>
            )}
            {!rasters.error && hasEntity && mapPanels.length === 0 && entityNames.length > 0 && (
              <div className="muted pad">
                Pick a {entityKind === "fleet" ? "fleet" : "group"} (step 3) to see a map.
              </div>
            )}
            {mapPanels.length > 0 && (
              <div className={`mapgrid mapgrid--${Math.min(mapPanels.length, 3)}`}>
                {mapPanels.map((p) => (
                  <div className="mapgrid__panel" key={p.key}>
                    <div className="mapgrid__title">
                      <span className="mapgrid__var">{formatLabel(variable)}</span>
                      {p.title && <span>{p.title}</span>}
                    </div>
                    <RasterMap
                      rasterUrl={p.rasterUrl}
                      prefetchUrl={p.prefetchUrl}
                      onStats={statsSetterFor(p.key)}
                      selectedAois={selectedAois}
                      onAoiDrawn={handleAoiDrawn}
                      palette={palette}
                      invert={invert}
                      domainOverride={domainOverride}
                      reloadToken={crsReloadToken}
                      onCrsFixed={() => setCrsReloadToken((t) => t + 1)}
                      viewSync={viewSync}
                    />
                    <RasterLegend
                      stats={statsByMap[p.key] ?? null}
                      unitLabel={formatLabel(variable)}
                      palette={palette}
                      invert={invert}
                    />
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
