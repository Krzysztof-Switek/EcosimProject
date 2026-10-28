import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { DimensionKind, DimensionOption } from "../../api/types";
import type { VariableKey } from "./catalogIndex";

export interface DimensionPicker {
  kind: DimensionKind;
  varCount: number; // selected variables that have this dimension
  options: DimensionOption[];
  loading: boolean;
  error: string | null;
  selected: Set<number>;
  /** The chosen ids still on offer -- what actually filters charts and the manifest. */
  effectiveIds: number[];
  toggle: (id: number) => void;
  setMany: (ids: number[], on: boolean) => void;
}

/**
 * Selection state for one EwE dimension (functional groups = step 5, fleets =
 * step 6): the options are the numbers actually present in the data of the
 * selected variables that have this dimension, across the scenarios they plot.
 * Cleared whenever `resetKey` changes (a data reload).
 */
export function useDimensionPicker(
  kind: DimensionKind,
  variables: VariableKey[], // selected, in the active freq
  scenariosFor: (v: VariableKey) => string[],
  freq: "annual" | "monthly",
  reloadToken: number,
  resetKey: unknown,
): DimensionPicker {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  useEffect(() => setSelected(new Set()), [resetKey]);

  const withDim = variables.filter((v) => (kind === "group" ? v.entry.n_groups : v.entry.n_fleets) > 0);
  // Fetched by primitive keys -- arrays rebuilt every render would refetch in a loop.
  const varKey = [...new Set(withDim.map((v) => v.variable))].sort().join("|");
  const scenarioKey = [...new Set(withDim.flatMap((v) => scenariosFor(v)))].sort().join("|");
  const options = useAsync(
    () =>
      varKey && scenarioKey
        ? api.dimension(kind, { variable: varKey.split("|"), freq, scenario: scenarioKey.split("|") })
        : Promise.resolve([]),
    [kind, varKey, scenarioKey, freq, reloadToken],
  );

  // Only ids still on offer count: a choice made for an earlier selection must
  // not keep filtering (or silently empty) the charts.
  const idKey = (options.data ?? [])
    .map((o) => o.id)
    .filter((id) => selected.has(id))
    .join("|");
  const effectiveIds = useMemo(() => (idKey ? idKey.split("|").map(Number) : []), [idKey]);

  return {
    kind,
    varCount: varKey ? varKey.split("|").length : 0,
    options: options.data ?? [],
    loading: options.loading,
    error: options.error,
    selected,
    effectiveIds,
    toggle: (id) =>
      setSelected((prev) => {
        const next = new Set(prev);
        next.has(id) ? next.delete(id) : next.add(id);
        return next;
      }),
    setMany: (ids, on) =>
      setSelected((prev) => {
        const next = new Set(prev);
        for (const id of ids) (on ? next.add(id) : next.delete(id));
        return next;
      }),
  };
}
