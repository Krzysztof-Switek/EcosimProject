import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartModel } from "./transform";

interface Props {
  model: ChartModel;
  yLabel: string;
  height?: number;
  showLegend?: boolean;
  /** A horizontal reference line (e.g. y = 1, the Ecopath state, for B/B0). */
  referenceY?: { y: number; label: string };
}

export function ComparisonChart({ model, yLabel, height = 420, showLegend = true, referenceY }: Props) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={model.data} margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
        <XAxis dataKey={model.xField} tick={{ fontSize: 12 }} minTickGap={24} />
        <YAxis
          tick={{ fontSize: 12 }}
          width={64}
          label={{ value: yLabel, angle: -90, position: "insideLeft", style: { fontSize: 12 } }}
        />
        <Tooltip
          formatter={(v) => (typeof v === "number" ? v.toPrecision(4) : String(v))}
          labelStyle={{ fontWeight: 600 }}
        />
        {showLegend && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {referenceY && (
          <ReferenceLine
            y={referenceY.y}
            stroke="#888"
            strokeDasharray="6 4"
            label={{ value: referenceY.label, position: "insideTopRight", fontSize: 11, fill: "#888" }}
          />
        )}
        {model.series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color}
            dot={false}
            strokeWidth={s.dashed ? 1.4 : 1.8}
            strokeDasharray={s.dashed ? "6 4" : undefined}
            connectNulls
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
