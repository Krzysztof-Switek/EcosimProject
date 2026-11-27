import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { Picks, SelectionEntity } from "../../api/types";
import type { VariableKey } from "./catalogIndex";
import { BOX_WINDOWS, CATEGORY_LABELS, type BoxWindow } from "./categories";

/** The selection of one Results-Extractor box (time-series step 5). */
export interface BoxSelection {
  box: string; // category id
  label: string; // box title
  window: BoxWindow;
  variables: VariableKey[]; // its checked variables -- the selection applies to all of them
  options: SelectionEntity[];
  loading: boolean;
  error: string | null;
  /** Chosen parents -> their chosen partners ([] in a one-level box). */
  chosen: Record<string, string[]>;
  /** The choice restricted to what is on offer -- what filters charts, analyses and downloads. */
  picks: Picks;
  toggleParent: (key: string) => void;
  toggleChild: (parent: string, child: string) => void;
  setChildren: (parent: string, children: string[]) => void;
  setAll: (on: boolean) => void;
  /** "Same for all": give every chosen parent this parent's partners (those it has). */
  copyToAll: (parent: string) => void;
}

const BOX_IDS = Object.keys(BOX_WINDOWS);

type Chosen = Record<string, Record<string, string[]>>; // box -> parent -> children

function effectivePicks(window: BoxWindow, options: SelectionEntity[], chosen: Record<string, string[]>): Picks {
  const picks: Picks = [];
  for (const o of options) {
    const children = chosen[o.key];
    if (!children) continue;
    if (!window.child) {
      picks.push([o.key]);
      continue;
    }
    const offered = new Set((o.children ?? []).map((c) => c.key));
    for (const c of children) if (offered.has(c)) picks.push([o.key, c]);
  }
  return picks;
}

/** An entity as the user reads it: EwE's name, else its number. */
export function entityLabel(kind: "group" | "fleet", e: { id: number | null; name: string | null; key: string }) {
  if (e.name) return e.name;
  if (e.id != null) return `${kind === "group" ? "Group" : "Fleet"} ${e.id}`;
  return e.key;
}

/**
 * Selection state of every Results-Extractor box: as in EwE, each box has one
 * selection ("Change Selection") applying to all its checked variables; its
 * options are the groups/fleets -- and in an "attached" box, per parent, the
 * partners -- present in those variables' data across the scenarios they plot.
 * Cleared whenever `resetKey` changes (a data reload).
 */
export function useBoxSelections(
  variables: VariableKey[], // selected, in the active freq
  scenariosFor: (v: VariableKey) => string[],
  freq: "annual" | "monthly",
  reloadToken: number,
  resetKey: unknown,
) {
  const [chosen, setChosen] = useState<Chosen>({});
  useEffect(() => setChosen({}), [resetKey]);

  // One options request per box, by primitive keys (arrays rebuilt every render
  // would refetch in a loop). BOX_IDS is constant, so the hooks run in a fixed order.
  // As in EwE, the window lists the model's groups/fleets whatever else is set:
  // until scenarios are chosen (steps 1–2), those of every scenario offering the
  // variables -- an empty window there read as "this variable has no groups".
  const requests = BOX_IDS.map((box) => {
    const vars = variables.filter((v) => v.domain === "output" && v.category === box);
    const chosenScenarios = vars.flatMap((v) => scenariosFor(v));
    return {
      box,
      vars,
      varKey: vars.map((v) => v.variable).sort().join("|"),
      scenarioKey: [...new Set(chosenScenarios.length ? chosenScenarios : vars.flatMap((v) => v.scenarios))]
        .sort()
        .join("|"),
    };
  });
  const results = requests.map(({ box, varKey, scenarioKey }) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useAsync(
      () =>
        varKey
          ? api.selection({ category: box, variable: varKey.split("|"), freq, scenario: scenarioKey.split("|") })
          : Promise.resolve([] as SelectionEntity[]),
      [box, varKey, scenarioKey, freq, reloadToken],
    ),
  );

  const update = useCallback(
    (box: string, fn: (cur: Record<string, string[]>) => Record<string, string[]>) =>
      setChosen((prev) => ({ ...prev, [box]: fn(prev[box] ?? {}) })),
    [],
  );

  const boxes: BoxSelection[] = requests.map(({ box, vars }, i) => {
    const window = BOX_WINDOWS[box];
    const options = results[i].data ?? [];
    const mine = chosen[box] ?? {};
    const childrenOf = (key: string) => (options.find((o) => o.key === key)?.children ?? []).map((c) => c.key);
    const without = (cur: Record<string, string[]>, key: string) => {
      const next = { ...cur };
      delete next[key];
      return next;
    };
    return {
      box,
      label: CATEGORY_LABELS[box] ?? box,
      window,
      variables: vars,
      options,
      loading: results[i].loading,
      error: results[i].error,
      chosen: mine,
      picks: effectivePicks(window, options, mine),
      // Checking a parent of an attached box takes all its partners; narrow them after.
      toggleParent: (key) =>
        update(box, (cur) => (key in cur ? without(cur, key) : { ...cur, [key]: window.child ? childrenOf(key) : [] })),
      toggleChild: (parent, child) =>
        update(box, (cur) => {
          const have = cur[parent] ?? [];
          const next = have.includes(child) ? have.filter((c) => c !== child) : [...have, child];
          return next.length ? { ...cur, [parent]: next } : without(cur, parent);
        }),
      setChildren: (parent, children) =>
        update(box, (cur) => (children.length ? { ...cur, [parent]: children } : without(cur, parent))),
      setAll: (on) =>
        update(box, () =>
          on ? Object.fromEntries(options.map((o) => [o.key, window.child ? childrenOf(o.key) : []])) : {},
        ),
      copyToAll: (parent) =>
        update(box, (cur) => {
          const wanted = new Set(cur[parent] ?? []);
          const next: Record<string, string[]> = {};
          for (const key of Object.keys(cur)) {
            const children = childrenOf(key).filter((c) => wanted.has(c));
            if (children.length) next[key] = children;
          }
          return next;
        }),
    };
  });

  const byBox = new Map(boxes.map((b) => [b.box, b]));

  /** A variable's picks: its box's selection, or undefined for a variable whose
   * box has no selection window (indicators, fitting statistics, drivers). */
  const picksFor = (v: VariableKey): Picks | undefined =>
    v.domain === "output" && v.category && BOX_WINDOWS[v.category] ? byBox.get(v.category)?.picks ?? [] : undefined;

  /** The selection as a person reads it, e.g. "JuvCod: AdCod_3, Grey seal; ..." (README). */
  const describe = (v: VariableKey): string => {
    const sel = v.category ? byBox.get(v.category) : undefined;
    if (!sel || !BOX_WINDOWS[v.category ?? ""]) return "all";
    const { window } = sel;
    const parts: string[] = [];
    for (const o of sel.options) {
      const kids = sel.picks.filter((p) => p[0] === o.key);
      if (!kids.length) continue;
      const name = entityLabel(window.kind, o);
      if (!window.child) parts.push(name);
      else {
        const names = kids.map((p) => {
          const c = o.children?.find((x) => x.key === p[1]);
          return c ? entityLabel(window.childKind ?? "group", c) : p[1];
        });
        parts.push(`${name}: ${names.join(", ")}`);
      }
    }
    return parts.join(window.child ? "; " : ", ") || "none";
  };

  return { boxes, picksFor, describe };
}
