import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type { AreaDefinition, AreaSummary, RegionLayer, RegionLayersForGrid, SavedArea } from "../../api/types";
import {
  type DraftGroup,
  draftName,
  draftToDefinition,
  drawnArea,
  drawnOnlyGeojson,
  emptyGroup,
  groupIsEmpty,
  makeAreaId,
  nextAreaName,
  uniqueName,
} from "./areaModel";

const SAVE_DELAY_MS = 400;

export interface AreaLibraryState {
  areas: SavedArea[];
  selected: string[];
  loaded: boolean;
  error: string | null;
  add: (name: string, area: AreaDefinition) => void;
  addDrawn: (geojson: GeoJSON.FeatureCollection, name?: string) => void;
  rename: (id: string, name: string) => void;
  remove: (id: string) => void;
  toggle: (id: string) => void;
  clearSelection: () => void;
}

/** The saved areas, kept in the profile (GET/PUT /areas) so analyses on the server see the same ones. */
export function useAreaLibrary(): AreaLibraryState {
  const [areas, setAreas] = useState<SavedArea[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = useRef(false);

  useEffect(() => {
    let cancelled = false;
    api
      .areaLibrary()
      .then((lib) => {
        if (cancelled) return;
        setAreas(lib.areas);
        setSelected(lib.selected);
        setLoaded(true);
      })
      .catch((err: Error) => !cancelled && setError(`Could not load your saved areas: ${err.message}`));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!loaded || !dirty.current) return;
    const timer = setTimeout(() => {
      dirty.current = false;
      api.saveAreaLibrary(areas, selected).then(
        () => setError(null),
        (err: Error) => setError(`Could not save your areas: ${err.message}`),
      );
    }, SAVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [areas, selected, loaded]);

  const change = useCallback((fn: () => void) => {
    dirty.current = true;
    fn();
  }, []);

  return {
    areas,
    selected,
    loaded,
    error,
    add: (name, area) =>
      change(() => {
        const id = makeAreaId();
        setAreas((prev) => [...prev, { id, name: uniqueName(name, prev), area }]);
        setSelected((prev) => [...prev, id]);
      }),
    addDrawn: (geojson, name) =>
      change(() => {
        const id = makeAreaId();
        setAreas((prev) => [
          ...prev,
          { id, name: name ? uniqueName(name, prev) : nextAreaName(prev), area: drawnArea(geojson) },
        ]);
        setSelected((prev) => [...prev, id]);
      }),
    rename: (id, name) => change(() => setAreas((prev) => prev.map((a) => (a.id === id ? { ...a, name } : a)))),
    remove: (id) =>
      change(() => {
        setAreas((prev) => prev.filter((a) => a.id !== id));
        setSelected((prev) => prev.filter((x) => x !== id));
      }),
    toggle: (id) =>
      change(() => setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))),
    clearSelection: () => change(() => setSelected([])),
  };
}

interface AreaShape {
  id: string;
  name: string;
  geojson: GeoJSON.FeatureCollection;
}

// Outlines are the same for the same area on the same scenario's grid --
// shared across maps and remounts.
const shapeCache = new Map<string, Promise<AreaSummary>>();

/**
 * The selected areas as lon/lat outlines on this scenario's grid: drawn shapes
 * as drawn; anything using reference areas as its cells' outline (from the
 * server, which knows the grid). ``problems``: why an area can't be shown.
 */
export function useAreaShapes(scenario: string | null, areas: SavedArea[]) {
  const [resolved, setResolved] = useState<Record<string, { summary?: AreaSummary; error?: string }>>({});
  const keys = useMemo(() => areas.map((a) => `${scenario}|${JSON.stringify(a.area)}`), [areas, scenario]);
  const signature = keys.join("\n");

  useEffect(() => {
    if (!scenario) return;
    let cancelled = false;
    areas.forEach((a, i) => {
      if (drawnOnlyGeojson(a.area)) return;
      const key = keys[i];
      let promise = shapeCache.get(key);
      if (!promise) {
        promise = api.areaSummary({ scenario, area: a.area, outline: true });
        shapeCache.set(key, promise);
        promise.catch(() => shapeCache.delete(key));
      }
      promise.then(
        (summary) => !cancelled && setResolved((r) => (r[key]?.summary ? r : { ...r, [key]: { summary } })),
        (err: Error) => !cancelled && setResolved((r) => ({ ...r, [key]: { error: err.message } })),
      );
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  return useMemo(() => {
    const shapes: AreaShape[] = [];
    const problems: Record<string, string> = {};
    const summaries: Record<string, AreaSummary> = {};
    areas.forEach((a, i) => {
      const drawn = drawnOnlyGeojson(a.area);
      if (drawn) {
        shapes.push({ id: a.id, name: a.name, geojson: drawn });
        return;
      }
      if (!scenario) {
        problems[a.id] = "Pick a scenario to place this area on the model's grid.";
        return;
      }
      const r = resolved[keys[i]];
      if (r?.error) problems[a.id] = r.error;
      else if (r?.summary) {
        summaries[a.id] = r.summary;
        if (r.summary.cells === 0) problems[a.id] = "No cells of this model's grid are in this area.";
        else if (r.summary.geojson) shapes.push({ id: a.id, name: a.name, geojson: r.summary.geojson });
      }
    });
    return { shapes, problems, summaries };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, resolved]);
}

/** What the map shows while an area is being put together from reference areas. */
export interface RegionMapOverlay {
  /** Outlines of the layer being picked from; clicking one toggles it. */
  outlines: GeoJSON.FeatureCollection | null;
  picked: string[];
  onToggle: (code: string) => void;
  /** The area so far, after intersections. */
  preview: GeoJSON.FeatureCollection | null;
}

const PREVIEW_DELAY_MS = 300;
const outlineCache = new Map<string, Promise<GeoJSON.FeatureCollection>>();

/** State of the "ICES & management areas" builder (lifted, so the map can show and edit it). */
export function useAreaBuilder(scenario: string | null, library: AreaLibraryState, active: boolean) {
  const layersState = useLayersForScenario(scenario);
  const layers = useMemo(() => layersState.data?.layers ?? [], [layersState.data]);
  const [draft, setDraft] = useState<DraftGroup[]>([emptyGroup()]);
  const [current, setCurrent] = useState(0);
  const [openLayer, setOpenLayer] = useState<string | null>(null);
  const [outlines, setOutlines] = useState<GeoJSON.FeatureCollection | null>(null);
  const [preview, setPreview] = useState<AreaSummary | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [nameEdited, setNameEdited] = useState(false);

  const group = draft[Math.min(current, draft.length - 1)];
  const definition = useMemo(() => draftToDefinition(draft, library.areas), [draft, library.areas]);
  const autoName = useMemo(() => draftName(draft, layers, library.areas), [draft, layers, library.areas]);
  const hasContent = !draft.every(groupIsEmpty);

  // A different grid (scenario) has other layers: start over.
  useEffect(() => {
    setDraft([emptyGroup()]);
    setCurrent(0);
    setOpenLayer(null);
  }, [layersState.data]);

  const openLayerObj: RegionLayer | null = layers.find((l) => l.key === openLayer) ?? null;
  useEffect(() => {
    if (!openLayerObj || !active) {
      setOutlines(null);
      return;
    }
    let cancelled = false;
    let promise = outlineCache.get(openLayerObj.id);
    if (!promise) {
      promise = api.regionOutlines(openLayerObj.id);
      outlineCache.set(openLayerObj.id, promise);
      promise.catch(() => outlineCache.delete(openLayerObj.id));
    }
    promise.then((fc) => !cancelled && setOutlines(fc), () => !cancelled && setOutlines(null));
    return () => {
      cancelled = true;
    };
  }, [openLayerObj, active]);

  const defSignature = JSON.stringify(definition);
  useEffect(() => {
    setPreviewError(null);
    if (!scenario || definition.groups.length === 0) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api.areaSummary({ scenario, area: definition, outline: true }).then(
        (s) => !cancelled && setPreview(s),
        (err: Error) => {
          if (cancelled) return;
          setPreview(null);
          setPreviewError(err.message);
        },
      );
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario, defSignature]);

  const updateGroup = (fn: (g: DraftGroup) => DraftGroup) =>
    setDraft((prev) => prev.map((g, i) => (i === Math.min(current, prev.length - 1) ? fn(g) : g)));

  const setCodes = (layerKey: string, codes: string[]) =>
    updateGroup((g) => ({ ...g, picks: { ...g.picks, [layerKey]: codes } }));

  const toggleCode = (layerKey: string, code: string) =>
    updateGroup((g) => {
      const now = g.picks[layerKey] ?? [];
      const next = now.includes(code) ? now.filter((c) => c !== code) : [...now, code];
      return { ...g, picks: { ...g.picks, [layerKey]: next } };
    });

  const toggleList = (field: "masks" | "saved", value: string) =>
    updateGroup((g) => ({
      ...g,
      [field]: g[field].includes(value) ? g[field].filter((v) => v !== value) : [...g[field], value],
    }));

  const reset = () => {
    setDraft([emptyGroup()]);
    setCurrent(0);
    setName("");
    setNameEdited(false);
  };

  const mapOverlay: RegionMapOverlay | null = useMemo(() => {
    if (!active) return null;
    const picked = openLayerObj && openLayerObj.kind === "regions" ? (group.picks[openLayerObj.key] ?? []) : [];
    return {
      outlines: openLayerObj?.kind === "regions" ? outlines : null,
      picked,
      onToggle: (code: string) => openLayerObj && toggleCode(openLayerObj.key, code),
      preview: preview?.geojson ?? null,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, openLayerObj, outlines, group, preview]);

  return {
    layers,
    grid: layersState.data?.grid ?? null,
    layersLoading: layersState.loading,
    layersError: layersState.error,
    draft,
    current: Math.min(current, draft.length - 1),
    setCurrent,
    group,
    openLayer,
    setOpenLayer: (key: string | null) => setOpenLayer((prev) => (prev === key ? null : key)),
    setCodes,
    toggleCode,
    toggleMask: (key: string) => toggleList("masks", key),
    toggleSaved: (id: string) => toggleList("saved", id),
    addGroup: () => {
      setDraft((prev) => [...prev, emptyGroup()]);
      setCurrent(draft.length);
    },
    removeGroup: (i: number) => {
      setDraft((prev) => (prev.length === 1 ? [emptyGroup()] : prev.filter((_, j) => j !== i)));
      setCurrent((c) => Math.max(0, c >= i ? c - 1 : c));
    },
    hasContent,
    preview: definition.groups.length > 0 ? preview : null,
    previewError,
    name: nameEdited ? name : autoName,
    setName: (v: string) => {
      setName(v);
      setNameEdited(true);
    },
    save: () => {
      library.add((nameEdited ? name : autoName).trim() || nextAreaName(library.areas), definition);
      reset();
      setOpenLayer(null);
    },
    reset,
    mapOverlay,
  };
}

export type AreaBuilderState = ReturnType<typeof useAreaBuilder>;

function useLayersForScenario(scenario: string | null) {
  const [state, setState] = useState<{ data: RegionLayersForGrid | null; loading: boolean; error: string | null }>({
    data: null,
    loading: false,
    error: null,
  });
  useEffect(() => {
    if (!scenario) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    api.regionLayers(scenario).then(
      (data) => !cancelled && setState({ data, loading: false, error: null }),
      (err: Error) => !cancelled && setState({ data: null, loading: false, error: err.message }),
    );
    return () => {
      cancelled = true;
    };
  }, [scenario]);
  return state;
}
