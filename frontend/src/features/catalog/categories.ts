// Output-variable categories: the boxes of the EwE "Results Extractor" window
// (User Guide, Results Extractor, Figure 1). Order is canonical; labels are the
// box titles. Backend (`catalog_datasets.category`) is the source of truth for
// assignment, and catalog/categories.py CATEGORY_DIMS for what each box selects.

export const CATEGORY_ORDER: { id: string; label: string }[] = [
  { id: "functional_groups", label: "Functional groups only" },
  { id: "predators_with_prey", label: "Predators with attached prey" },
  { id: "prey_with_predators", label: "Prey with attached predators" },
  { id: "fleets_only", label: "Fleets only" },
  { id: "fleets_with_prey", label: "Fleets with attached prey" },
  // Not a Results Extractor box: Ecospace's region age-structure tables.
  { id: "age_structure", label: "Age structure (Ecospace)" },
  { id: "fitting_stats", label: "Fitting statistics" },
  { id: "indicators", label: "Indicators" },
];

export const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORY_ORDER.map((c) => [c.id, c.label]),
);

/** A box's selection window: "simply double click on a group or use the arrows
 * ... to move the groups you want output for"; in an "attached" box "you first
 * select which predators you are interested [in], and then for each predator you
 * have selected, you select which prey" (UG p.129). One selection applies to all
 * checked variables of the box. Boxes absent here have no selection window. */
export interface BoxWindow {
  /** What the first column lists, plural and singular ("predators", "predator"). */
  parent: [string, string];
  /** "Attached" boxes: what is picked per parent. */
  child?: [string, string];
  /** How an unnamed entity is shown: EwE numbers groups and fleets separately. */
  kind: "group" | "fleet";
  childKind?: "group" | "fleet";
}

export const BOX_WINDOWS: Record<string, BoxWindow> = {
  functional_groups: { parent: ["groups", "group"], kind: "group" },
  predators_with_prey: { parent: ["predators", "predator"], child: ["prey", "prey"], kind: "group", childKind: "group" },
  prey_with_predators: { parent: ["prey", "prey"], child: ["predators", "predator"], kind: "group", childKind: "group" },
  fleets_only: { parent: ["fleets", "fleet"], kind: "fleet" },
  fleets_with_prey: { parent: ["fleets", "fleet"], child: ["groups", "group"], kind: "fleet", childKind: "group" },
  // a stanza group's monthly cohorts
  age_structure: { parent: ["groups", "group"], child: ["ages", "age"], kind: "group", childKind: "group" },
};
