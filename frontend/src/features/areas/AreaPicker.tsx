import { useRef, useState } from "react";
import type { AreaSummary, RegionLayer } from "../../api/types";
import { canJoin, describeDefinition, groupIsEmpty, usesLayers } from "./areaModel";
import type { AreaBuilderState, AreaLibraryState } from "./useAreas";

export type AreaPickerTab = "draw" | "regions";

/** Parse an uploaded area-of-interest file: GeoJSON directly, or a shapefile (.zip/.shp) via shpjs. */
async function parseAreaFile(file: File): Promise<GeoJSON.FeatureCollection> {
  const name = file.name.toLowerCase();
  if (name.endsWith(".geojson") || name.endsWith(".json")) {
    const parsed = JSON.parse(await file.text());
    return parsed.type === "FeatureCollection" ? parsed : { type: "FeatureCollection", features: [parsed] };
  }
  const shp = (await import("shpjs")).default;
  const result = await shp(await file.arrayBuffer());
  return Array.isArray(result) ? result[0] : result;
}

const fmt = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 0 });

function SizeLabel({ summary }: { summary: AreaSummary }) {
  return (
    <span className="muted">
      {fmt(summary.cells)} cells · {fmt(summary.area_km2)} km²
    </span>
  );
}

/**
 * Areas of interest, shared by the analyses: the saved areas (check any
 * number), drawn/uploaded shapes, and areas put together from reference
 * areas -- any ICES subdivisions/rectangles and management areas, joined
 * (union) and intersected.
 */
export function AreaPicker({
  library,
  builder,
  tab,
  onTab,
  problems,
  summaries,
}: {
  library: AreaLibraryState;
  builder: AreaBuilderState;
  tab: AreaPickerTab;
  onTab: (tab: AreaPickerTab) => void;
  problems: Record<string, string>;
  summaries: Record<string, AreaSummary>;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const upload = async (file: File) => {
    setUploadError(null);
    try {
      const geojson = await parseAreaFile(file);
      library.addDrawn(geojson, file.name.replace(/\.(geojson|json|zip|shp)$/i, "") || "Uploaded area");
    } catch (err) {
      setUploadError(`Could not read ${file.name}: ${(err as Error).message}`);
    }
  };

  return (
    <div className="areapicker">
      {library.error && <div className="error">{library.error}</div>}
      <div className="aoilist">
        {library.loaded && library.areas.length === 0 && <span className="muted">No saved areas yet.</span>}
        {library.areas.map((a) => {
          const description = usesLayers(a.area) ? describeDefinition(a.area, builder.layers) : null;
          const usesRegions = description !== null && description !== a.name;
          return (
            <div className="aoilist__entry" key={a.id}>
              <div className="aoilist__item">
                <input
                  type="checkbox"
                  checked={library.selected.includes(a.id)}
                  onChange={() => library.toggle(a.id)}
                />
                <input className="aoilist__name" value={a.name} onChange={(e) => library.rename(a.id, e.target.value)} />
                <button className="linkbtn aoilist__delete" onClick={() => library.remove(a.id)} title={`Delete "${a.name}"`}>
                  ✕
                </button>
              </div>
              {(usesRegions || summaries[a.id] || problems[a.id]) && (
                <div className="aoilist__meta">
                  {usesRegions && <span className="muted">{description}</span>}
                  {summaries[a.id] && <SizeLabel summary={summaries[a.id]} />}
                  {problems[a.id] && library.selected.includes(a.id) && (
                    <span className="aoilist__problem">{problems[a.id]}</span>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {library.selected.length > 0 && (
          <button className="linkbtn aoilist__clear" onClick={library.clearSelection}>
            Clear selection (show full map)
          </button>
        )}
      </div>

      <div className="areapicker__tabs" role="tablist">
        <button
          role="tab"
          aria-selected={tab === "draw"}
          className={`areapicker__tab${tab === "draw" ? " is-active" : ""}`}
          onClick={() => onTab("draw")}
        >
          Draw / upload
        </button>
        <button
          role="tab"
          aria-selected={tab === "regions"}
          className={`areapicker__tab${tab === "regions" ? " is-active" : ""}`}
          onClick={() => onTab("regions")}
        >
          ICES &amp; management areas
        </button>
      </div>

      {tab === "draw" && (
        <div className="aoictl__row">
          <button className="btn btn--ghost" onClick={() => fileInputRef.current?.click()}>
            Upload file
          </button>
          <span className="muted areapicker__hint">
            or draw on the map (polygon tool, top right): click each corner, then the first point again.
          </span>
          <input
            ref={fileInputRef}
            type="file"
            accept=".geojson,.json,.zip,.shp"
            className="aoictl__file-input"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void upload(file);
              e.target.value = "";
            }}
          />
          {uploadError && <div className="error">{uploadError}</div>}
        </div>
      )}

      {tab === "regions" && <RegionBuilder builder={builder} library={library} />}
    </div>
  );
}

function RegionBuilder({ builder, library }: { builder: AreaBuilderState; library: AreaLibraryState }) {
  const { grid, layers } = builder;
  if (builder.layersLoading && layers.length === 0) return <div className="muted">Loading reference areas…</div>;
  if (builder.layersError) return <div className="error">{builder.layersError}</div>;
  if (!grid) return <div className="muted">Pick a scenario first — areas are matched to its grid.</div>;
  if (grid.status !== "matched") {
    return (
      <div className="areapicker__notice">
        {grid.message}
        {grid.status === "no_match" && (
          <span className="muted"> Reference areas are loaded on the start page (“Reference areas”).</span>
        )}
      </div>
    );
  }

  const byCategory = new Map<string, RegionLayer[]>();
  for (const l of layers) byCategory.set(l.category, [...(byCategory.get(l.category) ?? []), l]);
  const joinable = library.areas.filter(canJoin);
  const g = builder.group;

  return (
    <div className="regionbuilder">
      <div className="regionbuilder__groups">
        {builder.draft.map((grp, i) => (
          <span key={i} className="regionbuilder__groupwrap">
            {i > 0 && <span className="regionbuilder__and" title="Intersection: only cells in both">∩</span>}
            <button
              className={`regionbuilder__group${i === builder.current ? " is-active" : ""}`}
              onClick={() => builder.setCurrent(i)}
              title={i === 0 ? "Regions joined together" : "…and only where they overlap with these"}
            >
              {groupIsEmpty(grp) ? (i === 0 ? "Pick areas" : "Pick areas to intersect with") : groupLabel(grp, layers)}
            </button>
            {builder.draft.length > 1 && (
              <button className="linkbtn" onClick={() => builder.removeGroup(i)} title="Remove this part">
                ✕
              </button>
            )}
          </span>
        ))}
        {!groupIsEmpty(builder.draft[builder.draft.length - 1]) && (
          <button className="linkbtn regionbuilder__intersect" onClick={builder.addGroup}>
            + Intersect with…
          </button>
        )}
      </div>
      <p className="muted regionbuilder__help">
        {builder.current === 0
          ? "Everything checked here is joined into one area."
          : "The area is cut to where it overlaps with what is checked here."}{" "}
        Open a layer to see it on the map — clicking a region there checks it.
      </p>

      {[...byCategory.entries()].map(([category, ls]) => (
        <div className="regionbuilder__category" key={category}>
          <div className="regionbuilder__cattitle">{category === "Management" ? "Management areas" : category}</div>
          {ls.map((layer) =>
            layer.kind === "regions" ? (
              <RegionLayerRow
                key={layer.id}
                layer={layer}
                open={builder.openLayer === layer.key}
                onOpen={() => builder.setOpenLayer(layer.key)}
                picked={g.picks[layer.key] ?? []}
                onToggle={(code) => builder.toggleCode(layer.key, code)}
                onSet={(codes) => builder.setCodes(layer.key, codes)}
              />
            ) : (
              <label
                className="check regionbuilder__mask"
                key={layer.id}
                title={Object.entries(layer.details).map(([k, v]) => `${k}: ${v}`).join("\n") || undefined}
              >
                <input
                  type="checkbox"
                  checked={g.masks.includes(layer.key)}
                  onChange={() => builder.toggleMask(layer.key)}
                  disabled={(layer.classes[0]?.cells ?? 0) === 0 && !g.masks.includes(layer.key)}
                />
                <span className={(layer.classes[0]?.cells ?? 0) === 0 ? "muted" : undefined}>{layer.title}</span>
                <span className="muted regionbuilder__count">
                  {(layer.classes[0]?.cells ?? 0) === 0 ? "not on this grid" : `${fmt(layer.classes[0].cells)} cells`}
                </span>
              </label>
            ),
          )}
        </div>
      ))}

      {joinable.length > 0 && (
        <div className="regionbuilder__category">
          <div className="regionbuilder__cattitle">Your saved areas</div>
          {joinable.map((a) => (
            <label className="check regionbuilder__mask" key={a.id}>
              <input type="checkbox" checked={g.saved.includes(a.id)} onChange={() => builder.toggleSaved(a.id)} />
              <span>{a.name}</span>
            </label>
          ))}
        </div>
      )}

      {builder.hasContent && (
        <div className="regionbuilder__result">
          <div>
            {builder.preview ? (
              builder.preview.cells === 0 ? (
                <span className="aoilist__problem">No cells — these parts don't overlap.</span>
              ) : (
                <>
                  Result: <SizeLabel summary={builder.preview} />
                </>
              )
            ) : builder.previewError ? (
              <span className="error">{builder.previewError}</span>
            ) : (
              <span className="muted">Counting cells…</span>
            )}
          </div>
          <input
            className="regionbuilder__name"
            value={builder.name}
            onChange={(e) => builder.setName(e.target.value)}
            placeholder="Name"
          />
          <div className="regionbuilder__actions">
            <button className="btn" onClick={builder.save} disabled={!builder.preview || builder.preview.cells === 0}>
              Save as area
            </button>
            <button className="btn btn--ghost" onClick={builder.reset}>
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function groupLabel(g: { picks: Record<string, string[]>; masks: string[]; saved: string[] }, layers: RegionLayer[]) {
  const parts: string[] = [];
  for (const [key, codes] of Object.entries(g.picks)) {
    if (codes.length === 0) continue;
    const layer = layers.find((l) => l.key === key);
    parts.push(codes.length <= 3 ? `${key === "ices_subdivisions" ? "SD " : ""}${codes.join("+")}` : `${codes.length} ${layer?.title ?? key}`);
  }
  for (const key of g.masks) parts.push(layers.find((l) => l.key === key)?.title ?? key);
  if (g.saved.length) parts.push(`${g.saved.length} saved area${g.saved.length === 1 ? "" : "s"}`);
  return parts.join(" + ");
}

function RegionLayerRow({
  layer,
  open,
  onOpen,
  picked,
  onToggle,
  onSet,
}: {
  layer: RegionLayer;
  open: boolean;
  onOpen: () => void;
  picked: string[];
  onToggle: (code: string) => void;
  onSet: (codes: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = q ? layer.classes.filter((c) => c.code.toLowerCase().includes(q) || c.label.toLowerCase().includes(q)) : layer.classes;
  return (
    <div className="regionlayer">
      <button className={`regionlayer__head${open ? " is-open" : ""}`} onClick={onOpen} aria-expanded={open}>
        <span className="regionlayer__caret">{open ? "▾" : "▸"}</span>
        <span>{layer.title}</span>
        <span className="muted regionbuilder__count">
          {picked.length > 0 ? `${picked.length} of ${layer.classes.length}` : layer.classes.length}
        </span>
      </button>
      {open && (
        <div className="regionlayer__body">
          <div className="regionlayer__tools">
            {layer.classes.length > 12 && (
              <input
                className="regionlayer__search"
                placeholder="Find a code…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            )}
            <button className="linkbtn" onClick={() => onSet([...new Set([...picked, ...shown.map((c) => c.code)])])}>
              All{q ? " found" : ""}
            </button>
            <button className="linkbtn" onClick={() => onSet(q ? picked.filter((p) => !shown.some((c) => c.code === p)) : [])}>
              None
            </button>
          </div>
          <div className="regionlayer__list">
            {shown.map((c) => (
              <label className="check regionlayer__class" key={c.code} title={c.label}>
                <input type="checkbox" checked={picked.includes(c.code)} onChange={() => onToggle(c.code)} />
                <span className="mono">{c.code}</span>
                <span className="muted regionbuilder__count">{fmt(c.cells)}</span>
              </label>
            ))}
            {shown.length === 0 && <span className="muted">No code matches.</span>}
          </div>
        </div>
      )}
    </div>
  );
}
