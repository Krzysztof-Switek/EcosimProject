import { useState } from "react";
import { api } from "../../api/client";
import type { Picks } from "../../api/types";
import type { VariableKey } from "../catalog/catalogIndex";
import { saveFile } from "../spatial/exportNames";
import type { Range } from "./VariableChart";

/**
 * The Results Extractor's "Save Results" (.CSV) with its "Yearly" option: the
 * selected series -- each variable's scenarios and box selection, the range --
 * as one CSV per variable in a zip with a README (backend
 * export/timeseries_csv.py). Yearly is "the mean over the year" of monthly data
 * (EwE User Guide, Results Extractor), so it is offered for monthly data only.
 */
export function SaveResults({
  variables,
  freq,
  range,
  run,
  scenariosFor,
  picksFor,
  describe,
}: {
  variables: VariableKey[];
  freq: "annual" | "monthly";
  range: Range;
  run?: string; // Monte Carlo: one run, else baseline + percentiles
  scenariosFor: (v: VariableKey) => string[];
  picksFor: (v: VariableKey) => Picks | undefined;
  describe: (v: VariableKey) => string;
}) {
  const monthly = freq === "monthly";
  const [yearly, setYearly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const items = variables.map((v) => ({
    v,
    variable: v.variable,
    scenarios: scenariosFor(v),
    picks: picksFor(v),
    selection: describe(v),
  }));
  const left = items.filter((i) => i.scenarios.length === 0 || (i.picks && i.picks.length === 0));
  const included = items.filter((i) => !left.includes(i));

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const { blob, filename } = await api.exportTimeseries({
        freq,
        yearly: monthly && yearly,
        run,
        ...range,
        items: included.map(({ variable, scenarios, picks, selection }) => ({ variable, scenarios, picks, selection })),
      });
      saveFile(blob, filename);
      setSaved(filename);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="field savectl">
      <label>Save results</label>
      <div className="muted savectl__note">.CSV · one file per variable, zipped with a README</div>
      <label className={`savectl__opt ${monthly ? "" : "is-disabled"}`}>
        <input type="checkbox" checked={monthly && yearly} disabled={!monthly} onChange={(e) => setYearly(e.target.checked)} />
        Yearly (mean over the year)
      </label>
      {!monthly && <div className="muted savectl__note">Yearly applies to monthly data (step 3).</div>}
      {left.length > 0 && (
        <div className="muted savectl__note">
          Left out, nothing selected: {left.map((i) => i.v.label).join(", ")}
        </div>
      )}
      <button className="btn" onClick={save} disabled={busy || included.length === 0}>
        {busy ? "Saving…" : `Save results (${included.length} variable${included.length === 1 ? "" : "s"})`}
      </button>
      {error && <div className="error">Failed: {error}</div>}
      {saved && <div className="muted savectl__note">Saved {saved}</div>}
    </div>
  );
}
