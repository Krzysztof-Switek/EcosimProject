import { gradientCss, type PaletteId } from "./colorScale";
import type { RasterStats } from "./RasterMap";

function formatValue(v: number): string {
  const abs = Math.abs(v);
  if (abs !== 0 && (abs < 0.001 || abs >= 100000)) return v.toExponential(2);
  return v.toLocaleString(undefined, { maximumFractionDigits: abs < 10 ? 3 : 1 });
}

export function RasterLegend({
  stats,
  unitLabel,
  palette,
  invert,
}: {
  stats: RasterStats | null;
  unitLabel: string;
  palette: PaletteId;
  invert: boolean;
}) {
  if (!stats) return null;
  return (
    <div className="legend">
      <div className="legend__label">{unitLabel}</div>
      <div className="legend__bar" style={{ background: gradientCss(palette, invert) }} />
      <div className="legend__ticks">
        <span>{formatValue(stats.min)}</span>
        <span>{formatValue(stats.max)}</span>
      </div>
    </div>
  );
}
