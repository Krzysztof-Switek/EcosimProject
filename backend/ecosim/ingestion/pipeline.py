"""Ingestion pipeline: raw ``DataEcosim/`` -> canonical Parquet store + catalog.

Idempotent. Discovers scenarios from ``output/`` (Ecosim CSVs) and ``input/``
(driver trend CSVs), normalises everything to the tidy schema, writes one
Parquet file per (scenario, domain, variable, freq), exports the dictionaries,
then rebuilds the DuckDB catalog.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ecosim.core.config import Settings, get_settings
from ecosim.core.schema import slugify
from ecosim.ingestion.parsers.ecosim_csv import parse_ecosim_csv, read_header
from ecosim.ingestion.parsers.group_map import Dictionaries, parse_group_map
from ecosim.ingestion.parsers.trend_csv import parse_trend_csv
from ecosim.ingestion.store import write_dataset


@dataclass
class IngestReport:
    scenarios: list[dict] = field(default_factory=list)
    datasets_written: int = 0
    rows_written: int = 0
    files_read: int = 0
    errors: list[str] = field(default_factory=list)


def _find_group_map(raw_dir: Path) -> Path:
    candidates = list(raw_dir.glob("Mapa_grupy_fleets.xlsx")) or list(raw_dir.rglob("Mapa_grupy_fleets.xlsx"))
    if not candidates:
        raise FileNotFoundError(f"Mapa_grupy_fleets.xlsx not found under {raw_dir}")
    return candidates[0]


def _discover_output(raw_dir: Path) -> list[tuple[str, str, Path]]:
    """Return (scenario_id, label, ecosim_dir) for each output scenario.

    The authoritative scenario name is the ``EcosimScenario`` field from the CSV
    ``"<HEADER ecosim/>"`` block (the official EwE name). The id is its slug; the
    label is the raw value. One parent folder may hold several runs (e.g.
    ``Baltic_Ecosim`` and ``baseline cumulative``) — distinct scenarios that must
    not be merged. Falls back to the directory name if the header is missing.
    """
    out: list[tuple[str, str, Path]] = []
    output_root = raw_dir / "output"
    if not output_root.exists():
        return out
    for top in sorted(p for p in output_root.iterdir() if p.is_dir()):
        ecosim_dirs = [d for d in top.rglob("ecosim_*") if d.is_dir() and any(d.glob("*.csv"))]
        for ecosim_dir in ecosim_dirs:
            csvs = sorted(ecosim_dir.glob("*.csv"))
            name = read_header(csvs[0]).get("EcosimScenario") if csvs else None
            if not name:
                name = ecosim_dir.name[len("ecosim_"):] if ecosim_dir.name.startswith("ecosim_") else ecosim_dir.name
            out.append((slugify(name), name, ecosim_dir))
    return out


def _discover_input(raw_dir: Path) -> list[tuple[str, str, Path]]:
    """Return (scenario_id, driver_variable, trend_csv_path) for input drivers."""
    out: list[tuple[str, str, Path]] = []
    input_root = raw_dir / "input"
    if not input_root.exists():
        return out
    for trend in sorted(input_root.rglob("trend_*.csv")):
        driver = trend.parent.name                 # e.g. "Bottom o2"
        scenario = slugify(trend.parent.parent.name)  # inner folder: BAU / HAS
        out.append((scenario, driver, trend))
    return out


def run_ingest(settings: Settings | None = None) -> IngestReport:
    settings = settings or get_settings()
    settings.ensure_dirs()
    report = IngestReport()

    dicts = parse_group_map(_find_group_map(settings.raw_dir))
    _export_dictionaries(dicts, settings.dictionaries_dir)

    seen_scenarios: dict[str, dict] = {}

    # Group raw sources by scenario so we can ingest one scenario at a time and
    # flush its datasets before moving on (bounds peak memory). Multi-file
    # variables (e.g. all predation_* targets) are concatenated per scenario.
    output_by_scenario: dict[str, list[Path]] = defaultdict(list)
    for scenario_id, label, ecosim_dir in _discover_output(settings.raw_dir):
        seen_scenarios.setdefault(scenario_id, {"id": scenario_id, "label": label, "domain": "output"})
        output_by_scenario[scenario_id].extend(sorted(ecosim_dir.glob("*.csv")))

    input_by_scenario: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for scenario_id, driver, trend_path in _discover_input(settings.raw_dir):
        seen_scenarios.setdefault(scenario_id, {"id": scenario_id, "label": scenario_id.upper(), "domain": "input"})
        input_by_scenario[scenario_id].append((driver, trend_path))

    for scenario_id, csv_paths in output_by_scenario.items():
        buckets: dict[tuple, list[pd.DataFrame]] = defaultdict(list)
        for csv_path in csv_paths:
            try:
                meta, df = parse_ecosim_csv(csv_path, dicts, scenario=scenario_id)
                report.files_read += 1
                if not df.empty:
                    buckets[(meta.variable, meta.freq)].append(df)
            except Exception as exc:  # noqa: BLE001 - collect and continue
                report.errors.append(f"{csv_path.name}: {exc}")
        _flush(buckets, settings, report)

    for scenario_id, drivers in input_by_scenario.items():
        buckets = defaultdict(list)
        for driver, trend_path in drivers:
            try:
                df = parse_trend_csv(trend_path, scenario=scenario_id, variable=driver)
                report.files_read += 1
                if not df.empty:
                    buckets[(slugify(driver), "annual")].append(df)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{trend_path.name}: {exc}")
        _flush(buckets, settings, report)

    report.scenarios = list(seen_scenarios.values())
    _export_scenarios(report.scenarios, settings.dictionaries_dir)

    # Build the catalog last, from the freshly written Parquet store.
    from ecosim.catalog.build import build_catalog

    build_catalog(settings)
    return report


def _flush(buckets: dict[tuple, list[pd.DataFrame]], settings: Settings, report: IngestReport) -> None:
    """Concatenate and write each accumulated (variable, freq) dataset, then drop it."""
    for frames in buckets.values():
        combined = pd.concat(frames, ignore_index=True)
        write_dataset(combined, settings.timeseries_dir)
        report.datasets_written += 1
        report.rows_written += len(combined)
    buckets.clear()


def _export_dictionaries(dicts: Dictionaries, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    dicts.groups.to_csv(out_dir / "groups.csv", index=False)
    dicts.fleets.to_csv(out_dir / "fleets.csv", index=False)


def _export_scenarios(scenarios: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(scenarios).to_csv(out_dir / "scenarios.csv", index=False)
