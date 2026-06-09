// Output-variable categories mirroring the EwE "Results Extractor" layout.
// Order is canonical; labels are the section headers shown in the catalog.
// Backend (`catalog_datasets.category`) is the source of truth for assignment.

export const CATEGORY_ORDER: { id: string; label: string }[] = [
  { id: "functional_groups", label: "Functional groups" },
  { id: "predators_with_prey", label: "Predators (with prey)" },
  { id: "prey_with_predators", label: "Prey (with predators)" },
  { id: "fleets_only", label: "Fleets" },
  { id: "fleets_with_prey", label: "Fleets (with prey)" },
  { id: "fitting_stats", label: "Fitting statistics" },
  { id: "indicators", label: "Indicators" },
];

export const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORY_ORDER.map((c) => [c.id, c.label]),
);
