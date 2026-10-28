import { Step } from "../../components/Step";
import { dimensionLabel } from "../timeseries/transform";
import type { DimensionPicker } from "./useDimensionPicker";

/** Sidebar step listing the groups or fleets (by EwE number) present in the
 * selected variables' data; hidden when no selected variable has the dimension. */
export function DimensionStep({
  n,
  title,
  picker,
  open,
  onToggle,
}: {
  n: number;
  title: string;
  picker: DimensionPicker;
  open: boolean;
  onToggle: () => void;
}) {
  const { kind, varCount, options, loading, error, selected, toggle, setMany } = picker;
  if (varCount === 0) return null;
  const allOn = options.length > 0 && options.every((o) => selected.has(o.id));
  const noun = kind === "group" ? "groups" : "fleets";

  return (
    <Step
      n={n}
      title={title}
      hint={`${picker.effectiveIds.length}/${options.length}`}
      open={open}
      onToggle={onToggle}
      bodyClassName="picker picker--compact"
    >
      {error && <div className="error pad">{error}</div>}
      {!error && loading && options.length === 0 && <div className="muted pad">Loading {noun}…</div>}
      {!error && !loading && options.length === 0 && (
        <div className="muted pad">no {noun} in the selected data</div>
      )}
      {options.length > 0 && (
        <div className="picker__group-head">
          <span className="picker__group-title">EwE {kind} number</span>
          <button className="linkbtn" onClick={() => setMany(options.map((o) => o.id), !allOn)}>
            {allOn ? "none" : "all"}
          </button>
        </div>
      )}
      {options.map((o) => {
        const partial = o.variables.length < varCount;
        return (
          <label
            key={o.id}
            className="picker__item"
            title={partial ? `Only in: ${o.variables.join(", ")}` : undefined}
          >
            <input type="checkbox" checked={selected.has(o.id)} onChange={() => toggle(o.id)} />
            <span className="picker__label">{dimensionLabel(kind, o.id, o.name)}</span>
            {partial && (
              <span className="badge badge--muted">
                {o.variables.length}/{varCount} var.
              </span>
            )}
          </label>
        );
      })}
    </Step>
  );
}
