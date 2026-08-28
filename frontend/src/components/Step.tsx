import type { ReactNode } from "react";

/** Collapsible numbered step with a header showing an optional hint (e.g. "2/3" or a current value). */
export function Step({
  n,
  title,
  hint,
  open,
  onToggle,
  bodyClassName = "picker",
  children,
}: {
  n?: number;
  title: string;
  hint?: string;
  open: boolean;
  onToggle: () => void;
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <div className="step">
      <button className="step__head step__head--btn" onClick={onToggle}>
        {n != null && <span className="step__n">{n}</span>}
        <span className="step__title">{title}</span>
        {hint && <span className="step__hint muted">{hint}</span>}
        <span className="catalog__chevron">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className={`step__body ${bodyClassName}`}>{children}</div>}
    </div>
  );
}
