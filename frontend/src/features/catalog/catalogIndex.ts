import type { ScenarioTreeNode, VariableEntry } from "../../api/types";

/** One (model, scenario) pair that offers a given variable+freq. */
export interface VariableCombo {
  model: string | null; // Ecopath model id (null for input drivers)
  model_name: string | null;
  scenario: string; // Ecosim scenario id (or driver scenario id)
}

export interface VariableKey {
  key: string; // `${domain}|${variable}|${freq}`
  domain: string;
  variable: string;
  freq: "annual" | "monthly";
  label: string;
  category: string | null; // Results-Extractor category (output only)
  entry: VariableEntry; // merged across scenarios
  combos: VariableCombo[]; // (model, scenario) pairs offering this variable+freq
  scenarios: string[]; // distinct scenario ids (derived from combos)
}

/**
 * Collapse the per-(model, scenario) tree into a global list of variables,
 * tracking which (model, scenario) combinations offer each one. The comparison
 * browser and the per-variable model/scenario picker both drive off `combos`.
 */
export function buildVariableIndex(tree: ScenarioTreeNode[]): VariableKey[] {
  const byKey = new Map<string, VariableKey>();

  for (const scn of tree) {
    for (const dom of scn.domains) {
      for (const v of dom.variables) {
        const key = `${dom.domain}|${v.variable}|${v.freq}`;
        const combo: VariableCombo = {
          model: scn.model,
          model_name: scn.model_name,
          scenario: scn.scenario,
        };
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
            combos: [combo],
            scenarios: [scn.scenario],
          });
        } else {
          existing.combos.push(combo);
          if (!existing.scenarios.includes(scn.scenario)) existing.scenarios.push(scn.scenario);
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
