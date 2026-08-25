// Sequential magnitude ramps (one hue, light -> dark) for raster maps.
// "blue" is the dataviz skill's validated reference palette (12 hand-tuned
// steps; see references/palette.md "Sequential hue" -- pre-validated, not
// re-checked here). The other hues aren't pre-baked in the skill, so they're
// built programmatically from the skill's documented categorical anchor hex
// by sweeping HSL lightness at a fixed hue -- monotonic lightness by
// construction, which is the actual sequential-ramp check (the skill's
// categorical validator doesn't apply to sequential ramps and would fail by
// design if run against one).
export type PaletteId = "blue" | "green" | "orange" | "red";

const BLUE_RAMP: string[] = [
  "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
  "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#0d366b",
];

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex(r: number, g: number, b: number): string {
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  switch (max) {
    case r: h = (g - b) / d + (g < b ? 6 : 0); break;
    case g: h = (b - r) / d + 2; break;
    default: h = (r - g) / d + 4;
  }
  return [h * 60, s, l];
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  h = ((h % 360) + 360) % 360 / 360;
  if (s === 0) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const hue2rgb = (t: number) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return [hue2rgb(h + 1 / 3) * 255, hue2rgb(h) * 255, hue2rgb(h - 1 / 3) * 255];
}

/** Build a single-hue sequential ramp from a documented anchor hex, sweeping
 * HSL lightness (high -> low) at that hue -- monotonic by construction. */
function buildSequentialRamp(anchorHex: string, steps = 9): string[] {
  const [h, s] = rgbToHsl(...hexToRgb(anchorHex));
  const satCapped = Math.min(s, 0.72);
  return Array.from({ length: steps }, (_, i) => {
    const l = 0.93 - (i / (steps - 1)) * 0.72; // near-white -> near-black, same hue
    return rgbToHex(...hslToRgb(h, satCapped, l)); // h is already in degrees (rgbToHsl's h*60)
  });
}

const PALETTES: Record<PaletteId, string[]> = {
  blue: BLUE_RAMP,
  green: buildSequentialRamp("#008300"), // categorical slot 6 (green)
  orange: buildSequentialRamp("#eb6834"), // categorical slot 2 (orange)
  red: buildSequentialRamp("#e34948"), // categorical slot 8 (red)
};

export const PALETTE_OPTIONS: { id: PaletteId; label: string }[] = [
  { id: "blue", label: "Blue" },
  { id: "green", label: "Green" },
  { id: "orange", label: "Orange" },
  { id: "red", label: "Red" },
];

/** Representative mid-tone hex per palette (its categorical anchor), for swatch buttons. */
export const PALETTE_SWATCH: Record<PaletteId, string> = {
  blue: "#2a78d6",
  green: "#008300",
  orange: "#eb6834",
  red: "#e34948",
};

const PALETTE_RGB: Record<PaletteId, [number, number, number][]> = Object.fromEntries(
  Object.entries(PALETTES).map(([id, hexes]) => [id, hexes.map(hexToRgb)]),
) as Record<PaletteId, [number, number, number][]>;

/** Linear-interpolate a palette at t in [0, 1] as an [r, g, b] byte triple. */
export function rampRgb(t: number, palette: PaletteId = "blue", invert = false): [number, number, number] {
  const stops = PALETTE_RGB[palette];
  const clamped = Math.max(0, Math.min(1, invert ? 1 - t : t));
  const scaled = clamped * (stops.length - 1);
  const i = Math.min(Math.floor(scaled), stops.length - 2);
  const frac = scaled - i;
  const [r0, g0, b0] = stops[i];
  const [r1, g1, b1] = stops[i + 1];
  return [
    Math.round(r0 + (r1 - r0) * frac),
    Math.round(g0 + (g1 - g0) * frac),
    Math.round(b0 + (b1 - b0) * frac),
  ];
}

/** CSS gradient string for a legend swatch, light (near-zero) -> dark (max). */
export function gradientCss(palette: PaletteId, invert: boolean): string {
  const hexes = PALETTES[palette];
  const ordered = invert ? [...hexes].reverse() : hexes;
  return `linear-gradient(to right, ${ordered.join(", ")})`;
}

/** Build a value -> [r, g, b] mapper for a given domain; null for nodata/invalid. */
export function makeValueToColor(
  min: number,
  max: number,
  noDataValue: number | null | undefined,
  palette: PaletteId = "blue",
  invert = false,
) {
  const span = max - min;
  return (value: number): [number, number, number] | null => {
    if (value == null || Number.isNaN(value)) return null;
    if (noDataValue != null && value === noDataValue) return null;
    const t = span > 0 ? (value - min) / span : 0;
    return rampRgb(t, palette, invert);
  };
}
