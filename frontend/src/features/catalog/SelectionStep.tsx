import { useEffect, useRef, useState } from "react";
import { Step } from "../../components/Step";
import type { SelectionEntity } from "../../api/types";
import { entityLabel, type BoxSelection } from "./useBoxSelections";

function TriCheck({ state, onChange }: { state: "all" | "some" | "none"; onChange: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === "some";
  }, [state]);
  return <input ref={ref} type="checkbox" checked={state === "all"} onChange={onChange} />;
}

function Partial({ entity, total }: { entity: SelectionEntity; total: number }) {
  if (entity.variables.length >= total) return null;
  return (
    <span className="badge badge--muted" title={`Only in: ${entity.variables.join(", ")}`}>
      {entity.variables.length}/{total} var.
    </span>
  );
}

/**
 * The selection window of one Results-Extractor box, as step 5 in the controls
 * column next to the sidebar (one per box with checked variables). A one-level box lists its groups or
 * fleets; an "attached" box lists the parents (predators, prey or fleets) and,
 * expanded, each one's own partners -- "for each predator you have selected, you
 * select which prey" (EwE User Guide, Results Extractor). The selection applies
 * to every checked variable of the box.
 */
export function SelectionStep({
  n,
  sel,
  open,
  onToggle,
}: {
  n: number;
  sel: BoxSelection;
  open: boolean;
  onToggle: () => void;
}) {
  const { window: w, options, chosen, picks, loading, error, variables } = sel;
  const [expanded, setExpanded] = useState<string | null>(null);
  const total = variables.length;
  const [parents, parent] = w.parent;
  const childKind = w.childKind ?? "group";

  const chosenParents = options.filter((o) => picks.some((p) => p[0] === o.key));
  const allOn = options.length > 0 && chosenParents.length === options.length &&
    (!w.child || picks.length === options.reduce((k, o) => k + (o.children?.length ?? 0), 0));
  const hint = w.child
    ? `${chosenParents.length}/${options.length} · ${picks.length} pairs`
    : `${picks.length}/${options.length}`;

  const parentState = (o: SelectionEntity): "all" | "some" | "none" => {
    if (!w.child) return o.key in chosen ? "all" : "none";
    const have = picks.filter((p) => p[0] === o.key).length;
    return have === 0 ? "none" : have === (o.children?.length ?? 0) ? "all" : "some";
  };

  return (
    <Step
      n={n}
      title={sel.label}
      hint={hint}
      open={open}
      onToggle={onToggle}
      bodyClassName="picker picker--compact"
    >
      <div className="selbox__for muted" title={variables.map((v) => v.label).join(", ")}>
        For: {variables.map((v) => v.label).join(", ")}
      </div>
      {error && <div className="error pad">{error}</div>}
      {!error && loading && options.length === 0 && <div className="muted pad">Loading {parents}…</div>}
      {!error && !loading && options.length === 0 && (
        <div className="muted pad">no {parents} in the selected data</div>
      )}
      {options.length > 0 && (
        <div className="picker__group-head">
          <span className="picker__group-title">
            {w.child ? `${parents[0].toUpperCase()}${parents.slice(1)}, then their ${w.child[0]}` : `EwE ${parents}`}
          </span>
          <button className="linkbtn" onClick={() => sel.setAll(!allOn)}>
            {allOn ? "none" : "all"}
          </button>
        </div>
      )}
      {options.map((o) => {
        const state = parentState(o);
        const isOpen = w.child && expanded === o.key;
        const kids = o.children ?? [];
        const mine = new Set(picks.filter((p) => p[0] === o.key).map((p) => p[1]));
        return (
          <div key={o.key} className={`selbox__parent ${isOpen ? "is-open" : ""}`}>
            <div className="picker__item">
              <TriCheck
                state={state}
                onChange={() => {
                  sel.toggleParent(o.key);
                  if (w.child && state === "none") setExpanded(o.key);
                }}
              />
              <span
                className={`picker__label ${w.child ? "selbox__expander" : ""}`}
                onClick={w.child ? () => setExpanded(isOpen ? null : o.key) : () => sel.toggleParent(o.key)}
              >
                {entityLabel(w.kind, o)}
              </span>
              <Partial entity={o} total={total} />
              {w.child && (
                <button
                  className={`selbox__count ${state !== "none" ? "is-on" : ""}`}
                  onClick={() => setExpanded(isOpen ? null : o.key)}
                  title={`Choose the ${w.child[0]} of this ${parent}`}
                >
                  {picks.filter((p) => p[0] === o.key).length}/{kids.length} {w.child[0]} {isOpen ? "▾" : "▸"}
                </button>
              )}
            </div>
            {isOpen && (
              <div className="selbox__children">
                <div className="picker__group-head">
                  <span className="picker__group-title">
                    {w.child![0][0].toUpperCase() + w.child![0].slice(1)} of {entityLabel(w.kind, o)}
                  </span>
                  <button
                    className="linkbtn"
                    onClick={() => sel.setChildren(o.key, mine.size === kids.length ? [] : kids.map((c) => c.key))}
                  >
                    {mine.size === kids.length ? "none" : "all"}
                  </button>
                </div>
                {kids.map((c) => (
                  <label key={c.key} className="picker__item">
                    <input type="checkbox" checked={mine.has(c.key)} onChange={() => sel.toggleChild(o.key, c.key)} />
                    <span className="picker__label">{entityLabel(childKind, c)}</span>
                    <Partial entity={c} total={total} />
                  </label>
                ))}
                {mine.size > 0 && chosenParents.length > 1 && (
                  <button
                    className="linkbtn selbox__copy"
                    onClick={() => sel.copyToAll(o.key)}
                    title={`Give every selected ${parent} these ${w.child![0]} (where it has them)`}
                  >
                    Same {w.child![0]} for all selected {parents}
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </Step>
  );
}
