"""Ingestion pipeline: raw model output/input data -> canonical Parquet
store + catalog.

Idempotent. Discovers scenarios from wherever the active *output* source's
Ecosim CSVs actually are and, if one is active, wherever the *input*
source's driver trend CSVs actually are -- see ``core/workspace.py`` for why
these are two independent sources rather than subfolders of one shared root.

Discovery is deliberately **content-driven, not folder-name-driven**: it
does not require an "output/"/"input/" subfolder, an "ecosim_<scenario>/"
folder, or any particular nesting depth. This was a real bug (27.08): the
first version required exactly the folder shape one example dataset
happened to use, and rejected a genuine Monte Carlo results folder organised
differently. Checked against the official EwE manual before rewriting (User
Guide p.50-51 Ecosampler, p.79-81 Multi-sim, p.265 Monte Carlo, p.275 basic
auto-save -- see docs/ewe-data-formats.md): EwE's own output location is a
user-configured setting with no fixed folder name anywhere, so a
folder-name requirement can only ever match how one export happened to be
organised, never what EwE output can generically look like.

Normalises everything found into the tidy schema, writes one Parquet file
per (scenario, domain, variable, freq), exports the dictionaries, then
rebuilds the DuckDB catalog.
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
    models: list[dict] = field(default_factory=list)
    datasets_written: int = 0
    rows_written: int = 0
    files_read: int = 0
    errors: list[str] = field(default_factory=list)
    # False when no Mapa_grupy_fleets.xlsx was found -- ingestion still ran
    # (see Dictionaries.empty()), but group_name/fleet_name columns are all
    # null; group_id/fleet_id (the real data) are unaffected. Surfaced as a
    # non-blocking note, not an error -- this dictionary is our own
    # convention, not something EwE itself requires or packages with output.
    group_dictionary_found: bool = True


def _find_group_map(root: Path) -> Path | None:
    candidates = list(root.glob("Mapa_grupy_fleets.xlsx")) or list(root.rglob("Mapa_grupy_fleets.xlsx"))
    return candidates[0] if candidates else None


def validate_output_root(path: Path) -> list[str]:
    """Cheap, synchronous check for "does this folder contain any real EwE
    output anywhere in it" -- used at source-registration time so a
    genuinely empty/unrelated folder is caught instantly instead of only
    surfacing as a silent zero-scenario ingest later. Returns human-readable
    problems; an empty list means it looks fine. Real ingestion still
    happens at activation.

    Deliberately requires no specific folder name ("output/") or nesting
    depth ("ecosim_<scenario>/") -- see this module's docstring for why: no
    such convention is documented anywhere in the official EwE manual, so
    requiring one can only ever match how a single example export happened
    to be organised. Purely content-driven instead: runs the exact same
    recursive discovery real ingestion uses
    (``_discover_output``/``_discover_output_rasters``), so it accepts
    whatever shape the data actually has, and only complains when nothing
    recognisable turns up anywhere in the tree.

    Also does not require ``Mapa_grupy_fleets.xlsx`` -- that dictionary is
    *this project's* own convention for resolving numeric group/fleet ids to
    names, not something EwE packages with its output at all (see
    ``docs/ewe-data-formats.md`` §5); ``run_ingest``/``build_raster_index``
    fall back to ``Dictionaries.empty()`` when it's missing (ids preserved,
    names left unresolved -- see that class).
    """
    from ecosim.ingestion.spatial_pipeline import _discover_output_rasters

    if not _discover_output(path) and not _discover_output_rasters(path):
        return [
            "No EwE output was found anywhere under this folder -- expected at "
            "least one .csv with an EcosimScenario header somewhere in it (e.g. "
            "biomass_annual.csv) or a .asc map with an Ecospace RunInfo.txt "
            "alongside it (e.g. EcospaceMapBiomass-*.asc). Check this is really "
            "your model's output."
        ]
    return []


def validate_input_root(path: Path) -> list[str]:
    """Same idea as ``validate_output_root``, for *Model input data*. No
    folder-name or nesting-depth requirement either -- see that function's
    docstring."""
    from ecosim.ingestion.spatial_pipeline import _discover_input_rasters

    if not _discover_input(path) and not _discover_input_rasters(path):
        return [
            "No driver data was found anywhere under this folder -- expected at "
            "least one trend_*.csv (e.g. trend_BAU.csv) or a driver .asc grid. "
            "Check this is really your model's input export."
        ]
    return []


@dataclass
class OutputRun:
    model_id: str
    model_label: str
    scenario_id: str
    scenario_label: str
    csv_paths: list[Path] = field(default_factory=list)


def _discover_output(output_raw_dir: Path) -> list[OutputRun]:
    """Discover each output run as an (Ecopath model, Ecosim scenario) pair
    by scanning every ``.csv`` anywhere under ``output_raw_dir`` and reading
    its own ``"<HEADER .../>"`` metadata -- not by assuming any folder name
    or nesting depth (see this module's docstring for why).

    Two authoritative header fields carried in every real CSV shape we've
    verified define the navigation hierarchy regardless of physical
    location: ``ModelName`` from ``"<HEADER ecopath/>"`` is the Ecopath
    model, and ``EcosimScenario`` from ``"<HEADER ecosim/>"`` is the
    scenario. Grouping is by that (model, scenario) *content* identity, not
    by which folder a file happens to sit in -- so scenarios scattered
    across however many levels of per-trial subfolders (Monte Carlo,
    Ecosampler, Multi-sim) are all found and correctly attributed together.
    A ``.csv`` with no ``EcosimScenario`` header is skipped: not every csv
    under a folder a user points at is necessarily EwE output, and this
    only claims to recognise what it can actually verify from the file
    itself.
    """
    if not output_raw_dir.exists():
        return []
    by_key: dict[tuple[str, str], OutputRun] = {}
    for csv_path in sorted(output_raw_dir.rglob("*.csv")):
        header = read_header(csv_path)
        scenario_label = header.get("EcosimScenario")
        if not scenario_label:
            continue
        model_label = header.get("ModelName") or "Unknown model"
        key = (slugify(model_label), slugify(scenario_label))
        run = by_key.get(key)
        if run is None:
            run = OutputRun(
                model_id=key[0], model_label=model_label,
                scenario_id=key[1], scenario_label=scenario_label,
            )
            by_key[key] = run
        run.csv_paths.append(csv_path)
    return list(by_key.values())


def _discover_input(input_raw_dir: Path) -> list[tuple[str, str, Path]]:
    """Return (scenario_id, driver_variable, trend_csv_path) for input
    drivers, scanning anywhere under ``input_raw_dir`` -- not assuming an
    "input/" folder name or fixed nesting depth (see this module's
    docstring). Unlike Ecosim output CSVs, these carry no embedded
    scenario/driver identity of their own (the row label is just a year --
    see ``parsers/trend_csv.py``): the file's own parent folder names the
    driver and its grandparent the scenario, an EwE-external convention
    that's kept since the file format genuinely has nothing else to go on,
    just without requiring it to sit a fixed number of levels under any
    particular root name.
    """
    out: list[tuple[str, str, Path]] = []
    if not input_raw_dir.exists():
        return out
    for trend in sorted(input_raw_dir.rglob("trend_*.csv")):
        driver = trend.parent.name                    # e.g. "Bottom o2"
        scenario = slugify(trend.parent.parent.name)   # e.g. BAU / HAS
        out.append((scenario, driver, trend))
    return out


def run_ingest(settings: Settings | None = None) -> IngestReport:
    settings = settings or get_settings()
    settings.ensure_dirs()
    report = IngestReport()

    # get_settings() guarantees output_raw_dir is set whenever it resolves at
    # all (see core/config.py); a bare Settings() built directly by a test/
    # script without one would fail here with a clear error, which is correct
    # -- there is nothing to ingest without an output source.
    #
    # The group/fleet dictionary is optional, not required: it's our own
    # convention for resolving numeric ids to names (EwE itself has none),
    # not something EwE ships with its output -- a real, valid output folder
    # (e.g. Monte Carlo results kept separately from wherever the modeller's
    # dictionary lives) must still ingest without it. group_id/fleet_id stay
    # populated either way; only *_name columns go null. See
    # Dictionaries.empty() and validate_output_root()'s docstring.
    dict_path = _find_group_map(settings.output_raw_dir)
    dicts = parse_group_map(dict_path) if dict_path else Dictionaries.empty()
    report.group_dictionary_found = dict_path is not None
    _export_dictionaries(dicts, settings.dictionaries_dir)

    seen_scenarios: dict[str, dict] = {}
    seen_models: dict[str, dict] = {}

    # Group raw sources by scenario so we can ingest one scenario at a time and
    # flush its datasets before moving on (bounds peak memory). Multi-file
    # variables (e.g. all predation_* targets) are concatenated per scenario.
    # Each output scenario also carries its parent Ecopath model.
    output_by_scenario: dict[str, list[Path]] = defaultdict(list)
    output_model: dict[str, tuple[str, str]] = {}  # scenario_id -> (model_id, model_label)
    for run in _discover_output(settings.output_raw_dir):
        seen_models.setdefault(run.model_id, {"id": run.model_id, "name": run.model_label})
        seen_scenarios.setdefault(run.scenario_id, {
            "id": run.scenario_id, "label": run.scenario_label, "domain": "output",
            "model": run.model_id, "model_name": run.model_label,
        })
        output_model[run.scenario_id] = (run.model_id, run.model_label)
        output_by_scenario[run.scenario_id].extend(run.csv_paths)

    input_by_scenario: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    if settings.input_raw_dir is not None:
        for scenario_id, driver, trend_path in _discover_input(settings.input_raw_dir):
            seen_scenarios.setdefault(scenario_id, {
                "id": scenario_id, "label": scenario_id.upper(), "domain": "input",
                "model": None, "model_name": None,
            })
            input_by_scenario[scenario_id].append((driver, trend_path))

    for scenario_id, csv_paths in output_by_scenario.items():
        model_id, model_label = output_model[scenario_id]
        buckets: dict[tuple, list[pd.DataFrame]] = defaultdict(list)
        for csv_path in csv_paths:
            try:
                meta, df = parse_ecosim_csv(
                    csv_path, dicts, scenario=scenario_id,
                    model=model_id, model_name=model_label,
                )
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
    report.models = list(seen_models.values())
    _export_scenarios(report.scenarios, settings.dictionaries_dir)
    _export_models(report.models, settings.dictionaries_dir)

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


def _export_models(models: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = ["id", "name"]
    df = pd.DataFrame(models, columns=cols) if models else pd.DataFrame(columns=cols)
    df.to_csv(out_dir / "models.csv", index=False)
