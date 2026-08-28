"""Job sandbox prep + execution for R analysis plugins.

Implements the contract in docs/data-contract.md: for each run, build
``job_<id>/{manifest.json, params.json, data/, out/}``, invoke the plugin's
entry script against it, then read back ``out/result.json``.

``run_job`` only cares about a script path on disk -- it has no idea whether
that path came from a registered plugin (today) or, later, a script an
in-browser editor wrote to a temp file. That door is left open by not baking
"resolve from the registry" into execution itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pandas as pd

from ecosim.analyses.registry import AnalysisSpec
from ecosim.catalog import service
from ecosim.core.config import Settings, get_settings

RSCRIPT_TIMEOUT_S = 300


class AnalysisRunError(RuntimeError):
    """Rscript exited non-zero, or out/result.json was never written."""


def _variable_names(manifest: dict) -> list[str]:
    """Manifest ``variables`` can be a flat list of slugs (docs/data-contract.md's
    own example) or a list of ``{variable, domain, scenarios}`` objects (what the
    time-series basket actually builds, since it lets each variable carry its own
    scenario selection) -- accept either."""
    names = []
    for v in manifest.get("variables") or []:
        names.append(v["variable"] if isinstance(v, dict) else v)
    return names


def rows_for_manifest(manifest: dict, settings: Settings | None = None) -> list[dict]:
    """Query the canonical store for exactly what a manifest selects -- the one
    place "manifest -> filtered tidy rows" is implemented, shared by sandbox prep
    (below) and the plain data-export endpoint (no R involved there at all)."""
    settings = settings or get_settings()
    freq = manifest.get("freq", "annual")
    rows: list[dict] = []
    for v in manifest.get("variables") or []:
        variable = v["variable"] if isinstance(v, dict) else v
        scenarios = v.get("scenarios") if isinstance(v, dict) else manifest.get("scenarios")
        rows += service.query_timeseries(
            settings,
            scenario=scenarios,
            variable=variable,
            freq=freq,
            group=manifest.get("groups"),
            fleet=manifest.get("fleets"),
            year_from=manifest.get("year_from"),
            year_to=manifest.get("year_to"),
            month_from=manifest.get("month_from"),
            month_to=manifest.get("month_to"),
        )
    return rows


def prepare_job(
    spec: AnalysisSpec,
    manifest: dict,
    params: dict,
    settings: Settings | None = None,
) -> Path:
    """Create a fresh job sandbox with filtered data + manifest/params, per the
    data contract. Returns the job directory."""
    settings = settings or get_settings()
    job_dir = settings.jobs_dir / f"job_{uuid.uuid4().hex[:12]}"
    data_dir = job_dir / "data"
    dict_dir = data_dir / "dictionaries"
    dict_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "out").mkdir(parents=True, exist_ok=True)

    (job_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (job_dir / "params.json").write_text(json.dumps(params, indent=2), encoding="utf-8")

    rows = rows_for_manifest(manifest, settings)
    if not rows:
        raise AnalysisRunError(
            "No data matched your selection (0 rows) -- check the scenario/variable/"
            "group/year filters and try a broader selection."
        )
    pd.DataFrame(rows).to_parquet(data_dir / "timeseries.parquet", index=False)

    pd.DataFrame(service.list_groups(settings)).to_csv(dict_dir / "groups.csv", index=False)
    pd.DataFrame(service.list_fleets(settings)).to_csv(dict_dir / "fleets.csv", index=False)
    pd.DataFrame(service.list_scenarios(settings)).to_csv(dict_dir / "scenarios.csv", index=False)

    return job_dir


def run_job(job_dir: Path, entry_path: Path, settings: Settings | None = None) -> None:
    """Invoke an R entry script against an already-prepared job sandbox.

    Only touches ``settings.ecosimkit_path``, which depends solely on
    ``project_root`` -- not on any active data source -- so a bare
    ``Settings()`` (not ``get_settings()``) is enough here; the sandbox at
    ``job_dir`` was already fully prepared (with real data) by
    ``prepare_job()`` before this runs.
    """
    settings = settings or Settings()
    env = {
        **os.environ,
        "ECOSIM_JOB_DIR": str(job_dir),
        "ECOSIM_KIT_PATH": str(settings.ecosimkit_path),
        # R's own error messages ("Error:", "Execution halted", ...) follow the
        # system locale by default -- force English so a raw R error surfaced
        # in the UI stays consistent with the English-only UI rule.
        "LANGUAGE": "en",
        "LC_MESSAGES": "C",
    }
    try:
        proc = subprocess.run(
            ["Rscript", str(entry_path)],
            cwd=job_dir,
            env=env,
            capture_output=True,
            # Explicit UTF-8, not text=True's locale-default decoding -- R's own
            # traceback rendering (box-drawing chars in dplyr/rlang errors) is
            # UTF-8 and came out as mojibake under Windows' default codepage.
            encoding="utf-8",
            errors="replace",
            timeout=RSCRIPT_TIMEOUT_S,
        )
    except FileNotFoundError as e:
        raise AnalysisRunError(
            "Rscript not found on PATH -- R must be installed to run analyses."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise AnalysisRunError(f"Analysis timed out after {RSCRIPT_TIMEOUT_S}s") from e
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-20:])
        raise AnalysisRunError(f"Rscript exited {proc.returncode}:\n{tail}")


def read_result(job_dir: Path) -> dict:
    result_path = job_dir / "out" / "result.json"
    if not result_path.exists():
        raise AnalysisRunError("Analysis did not write out/result.json")
    return json.loads(result_path.read_text(encoding="utf-8"))


def run_analysis(
    spec: AnalysisSpec,
    manifest: dict,
    params: dict,
    settings: Settings | None = None,
) -> dict:
    """Prepare a sandbox, run the entry script, return {job_id, result}."""
    settings = settings or get_settings()
    job_dir = prepare_job(spec, manifest, params, settings)
    run_job(job_dir, spec.entry_path, settings)
    result = read_result(job_dir)
    return {"job_id": job_dir.name, "result": result}
