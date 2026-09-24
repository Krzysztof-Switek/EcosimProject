import type { DataSource } from "../../api/types";

export function MonteCarloView({ activeOutput }: { activeOutput: DataSource | null }) {
  return (
    <div className="muted pad">
      {activeOutput
        ? `${activeOutput.run_count} samples loaded for ${activeOutput.name} — full comparison view is still in development.`
        : "Monte Carlo — compare the same scenario across multiple setups. Not built yet."}
    </div>
  );
}
