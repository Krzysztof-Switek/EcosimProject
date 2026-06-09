import { useMemo, useState } from "react";
import type { VariableKey } from "./catalogIndex";
import { CATEGORY_ORDER, CATEGORY_LABELS } from "./categories";

type Freq = "annual" | "monthly";

interface Props {
  variables: VariableKey[]; // already filtered to the active freq by App
  freq: Freq;
  onFreqChange: (f: Freq) => void;
  selectedIds: Set<string>; // `${domain}|${variable}` of checked variables
  onToggle: (id: string) => void;
}

const varId = (v: VariableKey) => `${v.domain}|${v.variable}`;

interface Section {
  id: string;
  title: string;
  items: VariableKey[];
}

/**
 * Ordered sections: output variables grouped by Results-Extractor category
 * (canonical order, empty categories omitted), then a single "Drivers (inputs)"
 * section. Anything unexpected falls into "Other model outputs".
 */
function buildSections(variables: VariableKey[]): Section[] {
  const byCategory = new Map<string, VariableKey[]>();
  const drivers: VariableKey[] = [];
  const other: VariableKey[] = [];

  for (const v of variables) {
    if (v.domain === "input") {
      drivers.push(v);
    } else if (v.category && CATEGORY_LABELS[v.category]) {
      let arr = byCategory.get(v.category);
      if (!arr) {
        arr = [];
        byCategory.set(v.category, arr);
      }
      arr.push(v);
    } else {
      other.push(v);
    }
  }

  const sections: Section[] = [];
  for (const cat of CATEGORY_ORDER) {
    const items = byCategory.get(cat.id);
    if (items && items.length) sections.push({ id: cat.id, title: cat.label, items });
  }
  if (other.length) sections.push({ id: "other", title: "Other model outputs", items: other });
  if (drivers.length) sections.push({ id: "input", title: "Drivers (inputs)", items: drivers });
  return sections;
}

/** Left-hand navigable index: freq toggle → collapsible category sections → variables. */
export function CatalogPanel({ variables, freq, onFreqChange, selectedIds, onToggle }: Props) {
  const [filter, setFilter] = useState("");
  // Accordion: all sections collapsed by default; user expands the ones they
  // want (several can stay open). An active text filter force-opens everything.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const sections = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const visible = f
      ? variables.filter((v) => v.label.toLowerCase().includes(f) || v.variable.includes(f))
      : variables;
    return buildSections(visible);
  }, [variables, filter]);

  const filtering = filter.trim().length > 0;
  const isOpen = (id: string) => filtering || expanded.has(id);

  const toggleSection = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <nav className="catalog">
      <div className="catalog__head">
        <strong>Variable catalog</strong>
        <div className="freqtoggle" role="tablist" aria-label="Frequency">
          <button
            className={`freqtoggle__btn ${freq === "annual" ? "is-active" : ""}`}
            onClick={() => onFreqChange("annual")}
          >
            Annual
          </button>
          <button
            className={`freqtoggle__btn ${freq === "monthly" ? "is-active" : ""}`}
            onClick={() => onFreqChange("monthly")}
          >
            Monthly
          </button>
        </div>
        <input
          className="catalog__filter"
          placeholder="filter variables…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <div className="catalog__list">
        {sections.map((section) => {
          const open = isOpen(section.id);
          return (
            <div key={section.id} className="catalog__group">
              <button
                className="catalog__group-title catalog__group-title--btn"
                onClick={() => toggleSection(section.id)}
              >
                <span className="catalog__chevron">{open ? "▾" : "▸"}</span>
                <span>{section.title}</span>
                <span className="catalog__count">{section.items.length}</span>
              </button>
              {open &&
                section.items.map((v) => {
                  const id = varId(v);
                  const checked = selectedIds.has(id);
                  return (
                    <label
                      key={v.key}
                      className={`catalog__item ${checked ? "is-active" : ""}`}
                    >
                      <input
                        type="checkbox"
                        className="catalog__check"
                        checked={checked}
                        onChange={() => onToggle(id)}
                      />
                      <span className="catalog__item-label">{v.label}</span>
                      <span className="catalog__badges">
                        <span className="badge badge--muted">{v.scenarios.length} scen.</span>
                      </span>
                    </label>
                  );
                })}
            </div>
          );
        })}
        {sections.length === 0 && <div className="muted pad">no variables</div>}
      </div>
    </nav>
  );
}
