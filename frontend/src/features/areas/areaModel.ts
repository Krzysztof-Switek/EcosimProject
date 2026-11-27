import type { AreaDefinition, AreaItem, RegionLayer, SavedArea } from "../../api/types";

/**
 * An area being put together from reference areas, before it's saved: a list
 * of groups, each the union of what's picked in it; the groups are then
 * intersected ("SD 25 + SD 26, and inside Natura 2000"). Saved as an
 * AreaDefinition (backend regions/masks.py).
 */
export interface DraftGroup {
  /** Region layer key -> picked region codes. */
  picks: Record<string, string[]>;
  /** Mask layer keys (0/1 layers, e.g. Natura 2000). */
  masks: string[];
  /** Saved areas joined into this group (only single-group ones can be). */
  saved: string[];
}

export const emptyGroup = (): DraftGroup => ({ picks: {}, masks: [], saved: [] });

export function groupIsEmpty(g: DraftGroup): boolean {
  return g.masks.length === 0 && g.saved.length === 0 && Object.values(g.picks).every((c) => c.length === 0);
}

export function draftToDefinition(draft: DraftGroup[], saved: SavedArea[]): AreaDefinition {
  const groups: AreaItem[][] = [];
  for (const g of draft) {
    const items: AreaItem[] = [];
    for (const [layer, codes] of Object.entries(g.picks)) {
      if (codes.length > 0) items.push({ kind: "regions", layer, codes: [...codes] });
    }
    for (const layer of g.masks) items.push({ kind: "regions", layer });
    for (const id of g.saved) {
      const area = saved.find((a) => a.id === id);
      if (area && area.area.groups.length === 1) items.push(...area.area.groups[0]);
    }
    if (items.length > 0) groups.push(items);
  }
  return { groups };
}

/** A saved area can be joined into a group only if it is itself one union (no intersection). */
export function canJoin(area: SavedArea): boolean {
  return area.area.groups.length === 1;
}

const CODE_PREFIX: Record<string, string> = { ices_subdivisions: "SD " };
const MAX_CODES_IN_NAME = 6;

function codesLabel(layerKey: string, codes: string[], layers: RegionLayer[]): string {
  const layer = layers.find((l) => l.key === layerKey);
  const prefix = CODE_PREFIX[layerKey] ?? (layerKey === "ices_rectangles" ? "" : `${layer?.title ?? layerKey}: `);
  const sorted = layer ? layer.classes.map((c) => c.code).filter((c) => codes.includes(c)) : codes;
  const shown = sorted.slice(0, MAX_CODES_IN_NAME).join("+");
  return `${prefix}${shown}${sorted.length > MAX_CODES_IN_NAME ? `+… (${sorted.length})` : ""}`;
}

function layerTitle(key: string, layers: RegionLayer[]): string {
  return layers.find((l) => l.key === key)?.title ?? key;
}

/** "SD 25+26 ∩ Natura 2000 (2024)" -- the default name of a draft. */
export function draftName(draft: DraftGroup[], layers: RegionLayer[], saved: SavedArea[]): string {
  return draft
    .filter((g) => !groupIsEmpty(g))
    .map((g) => {
      const parts = [
        ...Object.entries(g.picks).filter(([, c]) => c.length > 0).map(([k, c]) => codesLabel(k, c, layers)),
        ...g.masks.map((k) => layerTitle(k, layers)),
        ...g.saved.map((id) => saved.find((a) => a.id === id)?.name ?? "area"),
      ];
      const text = parts.join(" + ");
      return parts.length > 1 && draft.length > 1 ? `(${text})` : text;
    })
    .join(" ∩ ");
}

/** What a saved area is made of, for its line in the list ("SD 25+26 ∩ Natura 2000 (2024)"). */
export function describeDefinition(def: AreaDefinition, layers: RegionLayer[]): string {
  return def.groups
    .map((items) => {
      const parts = items.map((item) => {
        if (item.kind === "drawn") return "drawn shape";
        if (item.codes) return codesLabel(item.layer, item.codes, layers);
        return layerTitle(item.layer, layers);
      });
      const text = parts.join(" + ");
      return parts.length > 1 && def.groups.length > 1 ? `(${text})` : text;
    })
    .join(" ∩ ");
}

/** The polygon itself when the area is only drawn shapes (one union) -- no grid needed to show it. */
export function drawnOnlyGeojson(def: AreaDefinition): GeoJSON.FeatureCollection | null {
  if (def.groups.length !== 1 || !def.groups[0].every((i) => i.kind === "drawn")) return null;
  const features = def.groups[0].flatMap((i) => (i.kind === "drawn" ? i.geojson.features : []));
  return { type: "FeatureCollection", features };
}

/** Whether the area uses any reference-area layer (and so needs the model's grid to be shown). */
export function usesLayers(def: AreaDefinition): boolean {
  return def.groups.some((g) => g.some((i) => i.kind === "regions"));
}

export function drawnArea(geojson: GeoJSON.FeatureCollection): AreaDefinition {
  return { groups: [[{ kind: "drawn", geojson }]] };
}

let idSeq = 0;
export function makeAreaId(): string {
  idSeq += 1;
  return `aoi_${Date.now()}_${idSeq}`;
}

/** "Area 1", "Area 2", ... skipping any name already taken. */
export function nextAreaName(existing: { name: string }[]): string {
  const taken = new Set(existing.map((a) => a.name));
  let n = existing.length + 1;
  while (taken.has(`Area ${n}`)) n++;
  return `Area ${n}`;
}

/** A name not used yet: the given one, else "<name> (2)", "(3)"... */
export function uniqueName(name: string, existing: { name: string }[]): string {
  const taken = new Set(existing.map((a) => a.name));
  if (!taken.has(name)) return name;
  let n = 2;
  while (taken.has(`${name} (${n})`)) n++;
  return `${name} (${n})`;
}
