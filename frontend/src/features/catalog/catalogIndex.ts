import type { ScenarioTreeNode, VariableEntry } from "../../api/types";

export interface VariableKey {
  key: string; // `${domain}|${variable}|${freq}`
  domain: string;
  variable: string;
  freq: "annual" | "monthly";
  label: string;
  category: string | null; // Results-Extractor category (output only)
  entry: VariableEntry; // merged across scenarios
  scenarios: string[]; // scenarios offering this variable+freq
}

/**
 * Collapse the per-scenario tree into a global list of variables, tracking which
 * scenarios offer each one. This is what the comparison browser drives off of.
 */
export function buildVariableIndex(tree: ScenarioTreeNode[]): VariableKey[] {
  const byKey = new Map<string, VariableKey>();

  for (const scn of tree) {
    for (const dom of scn.domains) {
      for (const v of dom.variables) {
        const key = `${dom.domain}|${v.variable}|${v.freq}`;
        const existing = byKey.get(key);
        if (!existing) {
          byKey.set(key, {
            key,
            domain: dom.domain,
            variable: v.variable,
            freq: v.freq,
            label: v.label ?? v.variable,
            category: v.category,
            entry: { ...v },
            scenarios: [scn.scenario],
          });
        } else {
          existing.scenarios.push(scn.scenario);
          existing.entry.year_min = Math.min(existing.entry.year_min, v.year_min);
          existing.entry.year_max = Math.max(existing.entry.year_max, v.year_max);
          existing.entry.n_groups = Math.max(existing.entry.n_groups, v.n_groups);
          existing.entry.n_fleets = Math.max(existing.entry.n_fleets, v.n_fleets);
          existing.entry.n_partners = Math.max(existing.entry.n_partners, v.n_partners);
        }
      }
    }
  }

  return [...byKey.values()].sort(
    (a, b) =>
      a.domain.localeCompare(b.domain) ||
      a.label.localeCompare(b.label) ||
      a.freq.localeCompare(b.freq),
  );
}
