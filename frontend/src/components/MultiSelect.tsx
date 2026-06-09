import { useMemo, useState } from "react";

export interface Option {
  value: string;
  label: string;
}

interface Props {
  title: string;
  options: Option[];
  selected: string[];
  onChange: (next: string[]) => void;
  searchable?: boolean;
  /** Render as a collapsible dropdown (header toggles the checklist). */
  collapsible?: boolean;
}

/** Checklist with optional filter; optionally collapsible into a dropdown. */
export function MultiSelect({
  title,
  options,
  selected,
  onChange,
  searchable,
  collapsible,
}: Props) {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState(!collapsible);
  const sel = new Set(selected);

  const visible = useMemo(() => {
    if (!filter.trim()) return options;
    const f = filter.toLowerCase();
    return options.filter((o) => o.label.toLowerCase().includes(f));
  }, [options, filter]);

  const toggle = (value: string) => {
    const next = new Set(sel);
    next.has(value) ? next.delete(value) : next.add(value);
    onChange([...next]);
  };

  return (
    <div className={`multiselect ${collapsible ? "multiselect--dropdown" : ""}`}>
      {collapsible ? (
        <button
          type="button"
          className="multiselect__head multiselect__head--btn"
          onClick={() => setOpen((o) => !o)}
        >
          <span>{title}</span>
          <span className="multiselect__head-right">
            <span className="muted">{selected.length} selected</span>
            <span className="multiselect__chevron">{open ? "▾" : "▸"}</span>
          </span>
        </button>
      ) : (
        <div className="multiselect__head">
          <span>{title}</span>
          <span className="muted">{selected.length} selected</span>
        </div>
      )}

      {open && (
        <>
          {searchable && (
            <input
              className="multiselect__filter"
              placeholder="search…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          )}
          <div className="multiselect__list">
            {visible.map((o) => (
              <label key={o.value} className="multiselect__item">
                <input
                  type="checkbox"
                  checked={sel.has(o.value)}
                  onChange={() => toggle(o.value)}
                />
                <span>{o.label}</span>
              </label>
            ))}
            {visible.length === 0 && <div className="muted pad">no items</div>}
          </div>
        </>
      )}
    </div>
  );
}
