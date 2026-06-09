import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
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
}

export function ComparisonChart({ model, yLabel, height = 420, showLegend = true }: Props) {
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
        {model.series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color}
            dot={false}
            strokeWidth={1.8}
            connectNulls
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
