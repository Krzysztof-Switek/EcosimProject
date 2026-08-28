import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../api/useAsync";
import type { AnalysisResult } from "../../api/types";

/** Very small CSV -> table renderer, good enough for a plugin's own output
 * (small summary tables) without pulling in a CSV parsing dependency. */
function parseCsv(text: string): string[][] {
  return text
    .trim()
    .split("\n")
    .map((line) => line.split(","));
}

function ArtifactView({ jobId, artifact }: { jobId: string; artifact: AnalysisResult["artifacts"][number] }) {
  const csv = useAsync(
    () =>
      artifact.type === "table" && artifact.path
        ? fetch(api.artifactUrl(jobId, artifact.path)).then((r) => r.text())
        : Promise.resolve<string | null>(null),
    [jobId, artifact.path, artifact.type],
  );

  if (artifact.type === "figure" && artifact.path) {
    return (
      <div className="artifact">
        {artifact.title && <h3 className="artifact__title">{artifact.title}</h3>}
        <img className="artifact__figure" src={api.artifactUrl(jobId, artifact.path)} alt={artifact.title ?? "figure"} />
      </div>
    );
  }
  if (artifact.type === "table" && artifact.path) {
    const rows = csv.data ? parseCsv(csv.data) : null;
    return (
      <div className="artifact">
        {artifact.title && <h3 className="artifact__title">{artifact.title}</h3>}
        {!rows && <div className="muted">Loading table…</div>}
        {rows && (
          <div className="artifact__tablewrap">
            <table className="artifact__table">
              <thead>
                <tr>{rows[0].map((h, i) => <th key={i}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.slice(1).map((r, i) => (
                  <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }
  if (artifact.type === "scalar") {
    return (
      <div className="artifact artifact--scalar">
        {artifact.title && <div className="muted">{artifact.title}</div>}
        <div className="artifact__scalar">
          {artifact.value}
          {artifact.unit ? ` ${artifact.unit}` : ""}
        </div>
      </div>
    );
  }
  return (
    <div className="artifact muted">
      Unsupported artifact type "{artifact.type}"{artifact.title ? ` (${artifact.title})` : ""}.
    </div>
  );
}

async function downloadFile(res: Response, fallbackName: string) {
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const filename = match?.[1] ?? fallbackName;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Reusable "what do I do with my current selection" panel: run one of the R
 * analyses compatible with it, or just download the filtered data as a file.
 * Takes the manifest already built by the caller (the time-series basket
 * today; the spatial AOI selection later) -- this component never builds its
 * own, separate data selection, precisely so there's exactly one place per
 * module where you pick scenarios/variables/groups, not a second one hiding
 * behind "Analyses".
 */
export function AnalysisPanel({
  manifest,
  variableNames,
}: {
  manifest: Record<string, unknown>;
  /** Variable slugs currently selected -- used to filter to compatible analyses. */
  variableNames: string[];
}) {
  const analyses = useAsync(
    () => (variableNames.length > 0 ? api.analyses(variableNames) : Promise.resolve([])),
    [variableNames.join(",")],
  );
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const spec = useMemo(() => analyses.data?.find((a) => a.id === analysisId) ?? null, [analyses.data, analysisId]);

  const [paramValues, setParamValues] = useState<Record<string, unknown>>({});
  useEffect(() => {
    setParamValues(Object.fromEntries((spec?.params ?? []).map((p) => [p.key, p.default])));
  }, [spec]);

  // Default to the first compatible analysis once the list loads (or clear the
  // pick if it's no longer compatible with the current selection).
  useEffect(() => {
    const ids = new Set((analyses.data ?? []).map((a) => a.id));
    setAnalysisId((cur) => (cur && ids.has(cur) ? cur : (analyses.data?.[0]?.id ?? null)));
  }, [analyses.data]);

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [downloading, setDownloading] = useState(false);

  const run = async () => {
    if (!spec) return;
    setRunning(true);
    setRunError(null);
    setResult(null);
    try {
      const res = await api.runAnalysis(spec.id, { manifest, params: paramValues });
      setJobId(res.job_id);
      setResult(res.result);
    } catch (e) {
      setRunError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const download = async () => {
    setDownloading(true);
    setRunError(null);
    try {
      const res = await api.exportData(manifest);
      await downloadFile(res, "ecosim_export.csv");
    } catch (e) {
      setRunError((e as Error).message);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="analysispanel">
      <div className="analysispanel__row">
        <button className="btn btn--ghost" onClick={download} disabled={downloading}>
          {downloading ? "Downloading…" : "Download data (CSV)"}
        </button>

        {(analyses.data ?? []).length > 0 && (
          <>
            <select
              className="analysispanel__select"
              value={analysisId ?? ""}
              onChange={(e) => setAnalysisId(e.target.value)}
            >
              {analyses.data!.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            {spec?.params.map((p) => (
              <label className="analysispanel__param" key={p.key}>
                {p.type === "bool" ? (
                  <>
                    <input
                      type="checkbox"
                      checked={!!paramValues[p.key]}
                      onChange={(e) => setParamValues((v) => ({ ...v, [p.key]: e.target.checked }))}
                    />
                    {p.label ?? p.key}
                  </>
                ) : (
                  <>
                    {p.label ?? p.key}
                    <input
                      type="number"
                      className="analysispanel__paraminput"
                      value={String(paramValues[p.key] ?? "")}
                      onChange={(e) => setParamValues((v) => ({ ...v, [p.key]: Number(e.target.value) }))}
                    />
                  </>
                )}
              </label>
            ))}
            <button className="btn" onClick={run} disabled={running || !spec}>
              {running ? "Running…" : "Run analysis"}
            </button>
          </>
        )}
        {(analyses.data ?? []).length === 0 && variableNames.length > 0 && (
          <span className="muted">No analysis available for this selection yet.</span>
        )}
      </div>

      {runError && <div className="error">Failed: {runError}</div>}
      {result && jobId && (
        <div className="analysispanel__result">
          {result.title && <h3>{result.title}</h3>}
          {result.artifacts.map((a, i) => (
            <ArtifactView key={i} jobId={jobId} artifact={a} />
          ))}
        </div>
      )}
    </div>
  );
}
