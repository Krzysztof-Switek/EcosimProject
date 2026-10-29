/**
 * File names for exported data. Each one encodes the whole selection, so a
 * file stays identifiable once unpacked and mixed with others:
 *
 *   <area>__<model>__<scenario>__<variable>__<group or fleet>__<years>[__<colour scale>]
 *
 * Fields are separated by "__"; within a field only letters, digits, ".", "-"
 * and single "_" survive (anything else becomes "-"). Must stay in step with
 * backend/ecosim/export/spatial_ascii.py (name_part / file_stem), which names
 * the ASCII export the same way.
 */

export const FULL_AREA = "full-area";

export function namePart(text: string): string {
  const part = text
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/_{2,}/g, "_")
    .replace(/^[-._]+|[-._]+$/g, "");
  return part || "x";
}

export function fileStem(fields: {
  area: string;
  model: string | null;
  scenario: string;
  variable: string;
  entity: string | null;
  years: string;
  colour?: string;
}): string {
  const parts = [
    fields.area,
    fields.model ?? "no-model",
    fields.scenario,
    fields.variable,
    fields.entity ?? "all",
    fields.years,
  ];
  if (fields.colour) parts.push(fields.colour);
  return parts.map(namePart).join("__");
}

/** e.g. "blue_auto", "viridis-inverted_fixed_0_to_7.5" */
export function colourField(palette: string, invert: boolean, fixed: { min: number; max: number } | null): string {
  const scale = fixed ? `fixed_${fixed.min}_to_${fixed.max}` : "auto";
  return `${palette}${invert ? "-inverted" : ""}_${scale}`;
}

export function saveFile(data: Blob, filename: string) {
  const url = URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
