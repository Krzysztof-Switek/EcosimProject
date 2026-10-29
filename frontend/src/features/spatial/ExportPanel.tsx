import { useEffect, useMemo, useRef, useState } from "react";
import { strToU8, zipSync, type Zippable } from "fflate";
import { api } from "../../api/client";
import type { RasterEntry } from "../../api/types";
import type { PaletteId } from "./colorScale";
import { buildAnimations, ExportCancelled, type AnimationJob } from "./exportAnimation";
import { colourField, fileStem, FULL_AREA, namePart, saveFile } from "./exportNames";
import type { RasterStats } from "./RasterMap";

type Format = "ascii" | "gif";

interface Area {
  name: string;
  geojson: GeoJSON.FeatureCollection;
}

const entityOf = (r: RasterEntry) => r.group_name ?? r.fleet_name;

/** One checked variable with its own choices (SpatialView's VariableSettings). */
export interface ExportItem {
  variable: string;
  /** Checked groups/fleets; ignored for a variable without them. */
  entities: string[];
  yearFrom: number;
  yearTo: number;
  palette: PaletteId;
  invert: boolean;
  domainOverride: RasterStats | null;
}

/**
 * Download what's selected in the steps above -- each checked variable with
 * its own groups/fleets, year range and colour scale, and the areas of
 * interest (each area its own files; none = the whole model area):
 *  - ASCII grids: the model's own grid and values, for analysis elsewhere
 *    (built on the server from the raw .asc, see export/spatial_ascii.py);
 *  - animated GIF: the map animation as it plays on screen (built here, see
 *    exportAnimation.ts).
 * Every file name encodes the selection (exportNames.ts); the zip's
 * README.txt says how to read it.
 */
export function ExportPanel({
  scenario,
  model,
  items,
  labelOf,
  areas,
}: {
  scenario: string;
  model: string | null;
  items: ExportItem[];
  labelOf: (variable: string) => string;
  areas: Area[];
}) {
  const [format, setFormat] = useState<Format>("ascii");
  const [rastersByVariable, setRastersByVariable] = useState<Record<string, RasterEntry[]> | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const cancelRef = useRef(false);

  const variables = items.map((i) => i.variable);
  const variablesKey = variables.join("|");
  useEffect(() => {
    let cancelled = false;
    setRastersByVariable(null);
    Promise.all(variables.map((v) => api.spatialRasters({ scenario, variable: v })))
      .then((lists) => {
        if (!cancelled) setRastersByVariable(Object.fromEntries(variables.map((v, i) => [v, lists[i]])));
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario, variablesKey]);

  // What will be exported, per variable: the rasters in its year range, of its
  // checked groups/fleets (all of them for a variable without groups/fleets).
  // Every field, colour scale included: the GIF export reads each item's
  // palette from here, and a key of only variable/groups/years kept the
  // colours from before they were changed (every GIF came out in the default).
  const itemsKey = JSON.stringify(items);
  const selected = useMemo(() => {
    if (!rastersByVariable) return null;
    return items.map((item) => {
      const wanted = new Set(item.entities);
      const rows = (rastersByVariable[item.variable] ?? []).filter(
        (r) => r.year >= item.yearFrom && r.year <= item.yearTo && (entityOf(r) == null || wanted.has(entityOf(r)!)),
      );
      return { item, rows: rows.sort((a, b) => a.year - b.year) };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rastersByVariable, itemsKey]);

  const nAreas = Math.max(1, areas.length);
  const nMaps = selected ? selected.reduce((n, s) => n + s.rows.length, 0) : 0;
  const nAnimations = selected
    ? selected.reduce((n, s) => n + new Set(s.rows.map(entityOf)).size, 0) * nAreas
    : 0;
  const maxFrames = Math.max(0, ...items.map((i) => i.yearTo - i.yearFrom + 1));
  const skippedVariables = selected?.filter((s) => s.rows.length === 0).map((s) => labelOf(s.item.variable)) ?? [];

  // Per variable: what was chosen for it (README / selection.json).
  const selection = (withColour: boolean): ExportSelection => ({
    model,
    scenario,
    areas: areas.length > 0 ? areas.map((a) => a.name) : [`${FULL_AREA} (whole model area)`],
    variables: items.map((i) => ({
      variable: i.variable,
      groups_or_fleets: i.entities.length > 0 ? [...i.entities].sort() : "all",
      years: `${i.yearFrom}-${i.yearTo}`,
      ...(withColour ? { colour_scale: colourField(i.palette, i.invert, i.domainOverride) } : {}),
    })),
  });

  const downloadAscii = async () => {
    const { blob, filename } = await api.exportSpatialAscii({
      scenario,
      items: items.map((i) => ({
        variable: i.variable, entities: i.entities, year_from: i.yearFrom, year_to: i.yearTo,
      })),
      areas: areas.map((a) => ({ name: a.name, geojson: a.geojson })),
    });
    saveFile(blob, filename);
    setDone(`Saved ${filename}`);
  };

  const downloadGif = async () => {
    const areaList = areas.length > 0 ? areas.map((a) => ({ name: a.name, geojson: a.geojson })) : [{ name: FULL_AREA, geojson: null }];
    const jobs: AnimationJob[] = [];
    areaList.forEach((area, areaIndex) => {
      for (const { item, rows } of selected ?? []) {
        const colour = colourField(item.palette, item.invert, item.domainOverride);
        const byEntity = new Map<string | null, RasterEntry[]>();
        for (const r of rows) byEntity.set(entityOf(r), [...(byEntity.get(entityOf(r)) ?? []), r]);
        for (const [entity, rasters] of byEntity) {
          const stem = fileStem({
            area: area.name, model, scenario, variable: item.variable, entity,
            years: `${item.yearFrom}-${item.yearTo}`, colour,
          });
          jobs.push({
            area, areaIndex, variableLabel: labelOf(item.variable), entity, rasters,
            style: { title: scenario, palette: item.palette, invert: item.invert, domainOverride: item.domainOverride },
            fileName: `${namePart(area.name)}/${stem}.gif`,
          });
        }
      }
    });
    const { files, notes } = await buildAnimations(
      jobs,
      (d, t) => setProgress({ done: d, total: t }),
      () => cancelRef.current,
    );
    const zip: Zippable = {};
    for (const [name, bytes] of files) zip[name] = [bytes, { level: 0 }]; // GIF is already compressed
    const sel = selection(true);
    zip["README.txt"] = strToU8(gifReadme(sel, files.size, notes));
    zip["selection.json"] = strToU8(JSON.stringify({ ...sel, files: [...files.keys()], notes }, null, 2));
    const filename = `ecosim_gif__${namePart(scenario)}.zip`;
    saveFile(new Blob([zipSync(zip) as Uint8Array<ArrayBuffer>], { type: "application/zip" }), filename);
    setDone(`Saved ${filename}`);
  };

  const download = async () => {
    setBusy(true);
    setError(null);
    setDone(null);
    setProgress(null);
    cancelRef.current = false;
    try {
      await (format === "ascii" ? downloadAscii() : downloadGif());
    } catch (e) {
      setError(e instanceof ExportCancelled ? "Cancelled." : (e as Error).message);
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };

  return (
    <div className="exportctl">
      <div className="exportctl__formats">
        <label className="check">
          <input type="radio" name="export-format" checked={format === "ascii"} onChange={() => setFormat("ascii")} disabled={busy} />
          ASCII grids (.asc) — data values
        </label>
        <label className="check">
          <input type="radio" name="export-format" checked={format === "gif"} onChange={() => setFormat("gif")} disabled={busy} />
          Animated GIF — as on screen
        </label>
      </div>

      <div className="exportctl__summary muted">
        {areas.length > 0 ? `${areas.length} area${areas.length > 1 ? "s" : ""} (one file set each)` : "Whole model area"}
        {" · "}
        {variables.length} variable{variables.length === 1 ? "" : "s"}, each with its own groups, years and colours
        <br />
        {!selected
          ? "Counting maps…"
          : format === "ascii"
            ? `${nMaps * nAreas} .asc file${nMaps * nAreas === 1 ? "" : "s"} (one per map and year), with .prj and README.txt`
            : `${nAnimations} animation${nAnimations === 1 ? "" : "s"} of up to ${maxFrames} frames`}
        {skippedVariables.length > 0 && (
          <>
            <br />
            No checked group/fleet for: {skippedVariables.join(", ")}
          </>
        )}
      </div>
      {format === "gif" && selected && nMaps * nAreas > 60 && (
        <div className="exportctl__note muted">
          {nMaps * nAreas} frames are drawn in this browser, and maps not shown yet are converted on the server
          first — this can take a minute or two.
        </div>
      )}

      <div className="exportctl__actions">
        <button className="btn" onClick={download} disabled={busy || !selected || nMaps === 0}>
          {busy ? "Preparing…" : "Download .zip"}
        </button>
        {busy && format === "gif" && (
          <button className="linkbtn" onClick={() => (cancelRef.current = true)}>
            Cancel
          </button>
        )}
      </div>
      {progress && (
        <div className="exportctl__progress muted">
          Frame {progress.done} / {progress.total}
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {done && <div className="muted">{done}</div>}
    </div>
  );
}

function gifReadme(selection: ExportSelection, files: number, notes: string[]): string {
  const lines = [
    "Ecosim platform -- animated map export",
    `Created: ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`,
    "",
    "File names: <area>__<model>__<scenario>__<variable>__<group or fleet>__<years>__<colour scale>.gif",
    `  area           name of the area of interest, or '${FULL_AREA}' (the whole model area)`,
    "  group or fleet 'all' for a variable without groups/fleets",
    "  colour scale   <palette>[-inverted]_auto (each frame scaled to its own range, as on screen)",
    "                 or <palette>[-inverted]_fixed_<min>_to_<max>",
    "  Fields are separated by '__'. Spaces and other characters outside",
    "  A-Z a-z 0-9 . - _ are written as '-'.",
    "",
    "One frame per year, 0.7 s each (the on-screen speed). Background (c) OpenStreetMap contributors.",
    "",
    "Selection:",
    `  model: ${selection.model ?? "-"}`,
    `  scenario: ${selection.scenario}`,
    `  areas: ${selection.areas.join(", ")}`,
    ...selection.variables.flatMap((v) => [
      `  ${v.variable}:`,
      `    groups/fleets: ${Array.isArray(v.groups_or_fleets) ? v.groups_or_fleets.join(", ") : v.groups_or_fleets}`,
      `    years: ${v.years}`,
      ...(v.colour_scale ? [`    colour scale: ${v.colour_scale}`] : []),
    ]),
    "",
    `Files: ${files}`,
  ];
  if (notes.length > 0) lines.push("", "Notes:", ...notes.map((n) => `  ${n}`));
  return lines.join("\n") + "\n";
}

/** What was exported, as written to README.txt and selection.json. */
interface ExportSelection {
  model: string | null;
  scenario: string;
  areas: string[];
  variables: { variable: string; groups_or_fleets: string[] | string; years: string; colour_scale?: string }[];
}
