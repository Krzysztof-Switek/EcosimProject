import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { DimItem, RasterEntry } from "../../api/types";
import { Step } from "../../components/Step";
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

export function SpatialView({ groups, fleets }: { groups: DimItem[]; fleets: DimItem[] }) {
  const layers = useAsync(() => api.spatialLayers(), []);

  // Which numbered steps are collapsed -- starts with everything collapsed
  // (a step you open stays open until you close it again; nothing else auto-
  // collapses it), matching the timeseries Sidebar's Step behavior this view
  // already mirrors, but defaulting closed here to keep the sidebar short.
  const [collapsedSteps, setCollapsedSteps] = useState<Set<string>>(
    () => new Set(["scenario", "variable", "entity", "year", "color", "aoi"]),
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
  const [entity, setEntity] = useState<string | null>(null);
  // Same mark-for-later + click-to-focus pattern as selectedVariables, for
  // the Group/Fleet step.
  const [selectedEntities, setSelectedEntities] = useState<Set<string>>(new Set());
  const [year, setYear] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  // Custom sub-range within the available years (null = use the full
  // available range) -- lets the user narrow the slider/autoplay to only the
  // years they care about instead of always spanning everything on offer.
  const [customYearMin, setCustomYearMin] = useState<number | null>(null);
  const [customYearMax, setCustomYearMax] = useState<number | null>(null);
  const [stats, setStats] = useState<(RasterStats & { dataMin: number; dataMax: number }) | null>(null);
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

  // Marks can span both Group- and Fleet-typed variables (independent lists
  // sharing one Set -- marking "Ringed seal" while viewing a group-typed
  // variable and "Traps and pots" while viewing a fleet-typed one both land
  // in selectedEntities, which is fine). But anything RENDERED from that Set
  // must be filtered to the currently-focused variable's entity kind, or a
  // mark from the other kind leaks in as a bogus, clickable pill (e.g. a
  // group name offered as a "fleet"). entityNames is already scoped to
  // entityKind, so filter through it rather than reading selectedEntities raw.
  const visibleSelectedEntities = useMemo(
    () => entityNames.filter((n) => selectedEntities.has(n)),
    [entityNames, selectedEntities],
  );

  // Reset downstream selections when an upstream one changes.
  useEffect(() => {
    setVariable(null);
    setSelectedVariables(new Set());
    setEntity(null);
    setSelectedEntities(new Set());
    setYear(null);
    setPlaying(false);
  }, [scenario]);

  const toggleVariableSelected = (v: string) =>
    setSelectedVariables((prev) => {
      const next = new Set(prev);
      next.has(v) ? next.delete(v) : next.add(v);
      return next;
    });

  // Clicking a variable's name shows it on the map; it's implicitly marked
  // (checked) too, since viewing something usually means you care about it --
  // the checkbox stays there to mark others (or un-mark this one) separately.
  const focusVariable = (v: string) => {
    setVariable(v);
    setSelectedVariables((prev) => (prev.has(v) ? prev : new Set(prev).add(v)));
  };

  const toggleEntitySelected = (n: string) =>
    setSelectedEntities((prev) => {
      const next = new Set(prev);
      next.has(n) ? next.delete(n) : next.add(n);
      return next;
    });

  const focusEntity = (n: string) => {
    setEntity(n);
    setSelectedEntities((prev) => (prev.has(n) ? prev : new Set(prev).add(n)));
  };

  // Switching which marked variable is focused (checkbox stays, only the
  // shown one changes) must NOT wipe entity marks or the chosen year --
  // only things genuinely calibrated to one variable's data reset here: the
  // color-scale domain and the custom year sub-range (a fixed range or a
  // narrowed year window from Biomass rarely fits Catch). The entity/year
  // *values* persist -- see the fallback and clamp effects below.
  useEffect(() => {
    setPlaying(false);
    setDomainMode("auto");
    setManualMin("");
    setManualMax("");
    setCustomYearMin(null);
    setCustomYearMax(null);
  }, [variable]);

  const enableManualDomain = () => {
    if (stats) {
      setManualMin(String(stats.dataMin));
      setManualMax(String(stats.dataMax));
    }
    setDomainMode("manual");
  };

  // Keep the focused entity valid for whichever variable is now focused: if
  // it's still in this variable's entity list, leave it alone (this is what
  // makes a focus-switch preserve your place instead of jumping back to the
  // first group every time). Otherwise fall back to one that's already
  // marked and still valid, else the first available -- same as the
  // original first-ever pick, via the existing focusEntity() (which also
  // marks it). Also seeds the year on the very first pick.
  useEffect(() => {
    if (!activeLayer) return;
    if (hasEntity && entityNames.length > 0 && (entity == null || !entityNames.includes(entity))) {
      focusEntity(entityNames.find((n) => selectedEntities.has(n)) ?? entityNames[0]);
    }
    if (year == null) setYear(activeLayer.year_max);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeLayer, entityNames]);

  // Effective slider/autoplay bounds: the full available range, narrowed to
  // whatever the user typed into the range inputs (if anything).
  const yearLo = customYearMin ?? activeLayer?.year_min ?? 0;
  const yearHi = customYearMax ?? activeLayer?.year_max ?? 0;

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
              className={`catalog__item${variable === l.variable ? " is-active" : ""}`}
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
            </div>
          ))}
        </Step>

        {hasEntity && (
          <Step
            n={3}
            title={entityKind === "fleet" ? "Fleet" : "Group"}
            hint={visibleSelectedEntities.length > 0 ? `${visibleSelectedEntities.length} selected` : undefined}
            open={isStepOpen("entity")}
            onToggle={() => toggleStep("entity")}
          >
            {entityNames.map((n) => (
              <div key={n} className={`catalog__item${entity === n ? " is-active" : ""}`}>
                <input
                  type="checkbox"
                  className="catalog__check"
                  checked={selectedEntities.has(n)}
                  onChange={() => toggleEntitySelected(n)}
                />
                <span
                  className="catalog__item-label catalog__item-label--btn"
                  onClick={() => focusEntity(n)}
                  title={`Show this ${entityKind ?? "entity"} on the map`}
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
                    setCustomYearMin(Math.min(Math.max(v, activeLayer.year_min), yearHi));
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
                    setCustomYearMax(Math.max(Math.min(v, activeLayer.year_max), yearLo));
                  }}
                />
                <span className="muted">
                  (available: {activeLayer.year_min}–{activeLayer.year_max})
                </span>
                {(customYearMin != null || customYearMax != null) && (
                  <button
                    className="linkbtn"
                    onClick={() => {
                      setCustomYearMin(null);
                      setCustomYearMax(null);
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
      </aside>

      <main className="analysis__main spatialmain">
        {!scenario && (
          <div className="muted pad">Pick a scenario, then a variable, to see a map.</div>
        )}
        {scenario && variable && (
          <>
            {(selectedVariables.size > 1 || visibleSelectedEntities.length > 1) && (
              <div className="viewswitch">
                {selectedVariables.size > 1 && (
                  <div className="viewswitch__row">
                    <span className="viewswitch__label muted">Variable:</span>
                    {[...selectedVariables].map((v) => (
                      <button
                        key={v}
                        className={`viewswitch__pill${variable === v ? " is-active" : ""}`}
                        onClick={() => focusVariable(v)}
                      >
                        {formatLabel(v)}
                      </button>
                    ))}
                  </div>
                )}
                {visibleSelectedEntities.length > 1 && (
                  <div className="viewswitch__row">
                    <span className="viewswitch__label muted">
                      {entityKind === "fleet" ? "Fleet" : "Group"}:
                    </span>
                    {visibleSelectedEntities.map((n) => (
                      <button
                        key={n}
                        className={`viewswitch__pill${entity === n ? " is-active" : ""}`}
                        onClick={() => focusEntity(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            <RasterMap
              rasterUrl={rasterUrl}
              prefetchUrl={prefetchUrl}
              onStats={setStats}
              selectedAois={selectedAois}
              onAoiDrawn={handleAoiDrawn}
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
