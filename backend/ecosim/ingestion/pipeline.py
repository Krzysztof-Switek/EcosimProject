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
per (scenario, domain, variable, freq), exports the scenario/model
dimension tables, then rebuilds the DuckDB catalog.

No group/fleet name resolution happens here (removed 2026-08-28): EwE's own
output carries only numeric group/fleet ids, with no universal numbering
convention across models, so resolving them to names has always needed an
external lookup that isn't part of what Ecosim/Ecopath itself generates --
group_name/fleet_name simply stay null for shapes that don't carry a name in
the file already (wide-by-name/predation and raster filenames still do, and
still resolve, straight from that content). See
docs/Plans and TO_DO lists/28.08_session_summary.md.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

# (phase, files_done, files_total_or_None) -- called periodically (not on
# every single file, for very large trees) so a caller can surface live
# progress instead of the request looking hung. files_total is None during
# discovery (not known yet -- see module docstring) and a real count once
# processing starts.
ProgressFn = Callable[[str, int, int | None], None]

from ecosim.core.config import Settings, get_settings
from ecosim.core.schema import slugify
from ecosim.ingestion.file_access import UnreadableFileError, describe_read_error, is_cloud_only
from ecosim.ingestion.parsers.ecosim_csv import UnsupportedCsvShape, parse_ecosim_csv, read_header
from ecosim.ingestion.parsers.trend_csv import parse_trend_csv
from ecosim.ingestion.store import write_dataset


class IngestCancelled(Exception):
    """Raised at a progress checkpoint when the caller's ``cancel_event`` is
    set, so a background activation stops promptly instead of running to
    completion. Deliberately a distinct type from any parsing/IO error --
    ``activation.py`` catches this separately to record status="cancelled"
    rather than "error" (the user asked to stop; nothing went wrong)."""


@dataclass
class IngestReport:
    scenarios: list[dict] = field(default_factory=list)
    models: list[dict] = field(default_factory=list)
    datasets_written: int = 0
    rows_written: int = 0
    files_read: int = 0
    errors: list[str] = field(default_factory=list)
    # Files recognised as a known-but-unsupported shape (see
    # parsers.ecosim_csv.UnsupportedCsvShape's docstring for the two real
    # cases) -- counted separately from `errors` since these aren't broken
    # files, just ones this pipeline doesn't turn into tidy rows (yet, for
    # region/age-structure; never, for the Ecospace map-as-CSV duplicate).
    skipped_unsupported: int = 0
    # True when any scenario's files were found living under 2+ distinct
    # directories -- real Monte Carlo/Ecosampler data (verified 2026-08-28
    # against a real ~58-sample dataset), not a single ordinary run. See
    # OutputRun.run_dirs and core/schema.py's run_id docstring note.
    has_multiple_runs: bool = False
    # Distinct run directories seen for whichever scenario spans the most --
    # 1 for ordinary single-run data. See ``run_count`` on
    # ``ingestion.activation.ActivationResult``, which surfaces this on the
    # Monte Carlo tile as "N samples".
    run_count: int = 1


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
    to be organised. Content-driven, same as real discovery, but a genuine
    *existence* check, not full discovery: stops at the first valid file
    found instead of reading every ``.csv``'s header and materializing a
    fully sorted listing like ``_discover_output`` does -- for a folder with
    hundreds of thousands of files (a real 2026-08-28 case, ~400GB/800k+
    files on a synced OneDrive path) that difference is the whole
    registration hanging for a very long time vs. resolving almost
    instantly. See ``_any_output_csv``/``_any_output_raster``.

    Never required (or looked for) any external group/fleet name dictionary
    either -- EwE packages no such thing with its own output, and this
    pipeline no longer has any mechanism to consume one even if a user
    supplied one (removed 2026-08-28; see
    docs/Plans and TO_DO lists/28.08_session_summary.md). group_id/fleet_id
    are always preserved from the raw numeric data; group_name/fleet_name
    resolve only where EwE's own files already carry a name directly
    (predation/prey column headers, Ecospace raster filenames) and stay null
    otherwise.
    """
    from ecosim.ingestion.spatial_pipeline import _any_output_raster

    unreadable: list[str] = []
    not_local: list[Path] = []
    if not _any_output_csv(path, unreadable, not_local) and not _any_output_raster(path):
        if not_local:
            # Can't judge content that isn't on this computer yet -- reading
            # it here would itself start a download. The real scan (after
            # the files are downloaded) still refuses a folder with no EwE
            # output in it, see activation._ingest_one_source.
            return []
        problem = (
            "No EwE output was found anywhere under this folder -- expected at "
            "least one .csv with an EcosimScenario header somewhere in it (e.g. "
            "biomass_annual.csv) or a .asc map with an Ecospace RunInfo.txt "
            "alongside it (e.g. EcospaceMapBiomass-*.asc). Check this is really "
            "your model's output."
        )
        if unreadable:
            # Not "no output here" -- possibly just "none of it readable",
            # which is a different fix entirely (see file_access.py).
            problem += f" Note: {len(unreadable):,} file(s) could not be read at all. First one: {unreadable[0]}"
        return [problem]
    return []


def _any_output_csv(
    root: Path, unreadable: list[str] | None = None, not_local: list[Path] | None = None,
) -> bool:
    """True as soon as one ``.csv`` with a real ``EcosimScenario`` header is
    found anywhere under ``root`` -- an existence check, not discovery, so it
    doesn't matter which one is found first (unlike ``_discover_output``,
    order/completeness is irrelevant here). Iterates the raw ``rglob``
    generator directly rather than ``sorted(...)``, which would force the
    entire tree to be walked and held in memory before checking anything.

    A file that can't be read is skipped rather than failing registration
    (another one may well be readable -- this only asks "is there anything
    here at all"); its human-readable reason is appended to ``unreadable``
    so the caller can explain an empty result honestly. The full scan still
    stops on it later, with the same message.

    Cloud-only files (see ingestion/file_access.py) are never opened here --
    opening one makes the sync app download it -- only collected into
    ``not_local``."""
    if not root.exists():
        return False
    for csv_path in root.rglob("*.csv"):
        if is_cloud_only(csv_path):
            if not_local is not None:
                not_local.append(csv_path)
            continue
        try:
            header = read_header(csv_path)
        except OSError as exc:
            if unreadable is not None:
                unreadable.append(describe_read_error(exc, csv_path, root))
            continue
        if header.get("EcosimScenario"):
            return True
    return False


def validate_input_root(path: Path) -> list[str]:
    """Same idea as ``validate_output_root``, for *Model input data*: a
    genuine existence check, not full discovery -- see that function's
    docstring for why this matters at scale."""
    from ecosim.ingestion.spatial_pipeline import _any_input_raster

    if not _any_input_csv(path) and not _any_input_raster(path):
        return [
            "No driver data was found anywhere under this folder -- expected at "
            "least one trend_*.csv (e.g. trend_BAU.csv) or a driver .asc grid. "
            "Check this is really your model's input export."
        ]
    return []


def _any_input_csv(root: Path) -> bool:
    """True as soon as one ``trend_*.csv`` exists anywhere under ``root`` --
    no file content check needed, ``_discover_input`` doesn't validate
    content beyond the filename pattern either, so this is just the first
    match from the glob itself (no per-file I/O at all)."""
    if not root.exists():
        return False
    for _ in root.rglob("trend_*.csv"):
        return True
    return False


@dataclass
class OutputRun:
    model_id: str
    model_label: str
    scenario_id: str
    scenario_label: str
    csv_paths: list[Path] = field(default_factory=list)
    # Distinct parent directories (relative to output_raw_dir) seen among
    # this scenario's csv_paths so far -- 2+ means this scenario's files
    # come from multiple runs (Monte Carlo/Ecosampler), not one ordinary
    # run split across several unrelated variable files. See run_ingest()'s
    # use of this to decide whether run_id needs populating at all.
    run_dirs: set[str] = field(default_factory=set)


_PROGRESS_EVERY = 200  # throttle: report every N files, not every single one


def _discover_output(
    output_raw_dir: Path,
    on_progress: ProgressFn | None = None,
    cancel_event: threading.Event | None = None,
) -> list[OutputRun]:
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

    Unlike ``_any_output_csv``, this genuinely has to read every file's
    header (there's no way to know the full set of scenarios without it),
    so for a very large tree this alone can take a while with nothing else
    happening yet -- ``on_progress`` reports a running "still working"
    count (``files_total=None``, the total isn't known until this finishes)
    so a caller can show live movement instead of dead silence.
    """
    if not output_raw_dir.exists():
        return []
    by_key: dict[tuple[str, str], OutputRun] = {}
    seen = 0
    for csv_path in sorted(output_raw_dir.rglob("*.csv")):
        if cancel_event is not None and seen % _PROGRESS_EVERY == 0 and cancel_event.is_set():
            raise IngestCancelled()
        try:
            header = read_header(csv_path)
        except OSError as exc:
            # Stop, don't skip: an unreadable file could be any scenario's
            # output, so carrying on would silently load an incomplete
            # dataset. The message names the file and the cause -- a bare
            # OSError here once reached the UI as just "[Errno 22] Invalid
            # argument" (see file_access.py).
            raise UnreadableFileError(describe_read_error(exc, csv_path, output_raw_dir)) from exc
        seen += 1
        if on_progress is not None and seen % _PROGRESS_EVERY == 0:
            on_progress("discovering_output", seen, None)
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
        run.run_dirs.add(str(csv_path.parent.relative_to(output_raw_dir)))
    if on_progress is not None:
        on_progress("discovering_output", seen, None)
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


def run_ingest(
    settings: Settings | None = None,
    on_progress: ProgressFn | None = None,
    cancel_event: threading.Event | None = None,
) -> IngestReport:
    """``on_progress(phase, done, total)`` -- optional, called periodically
    (not every file, for very large trees) so a caller running this in the
    background can surface live progress instead of a request that just
    looks hung. ``total`` is ``None`` during discovery (the full file set
    isn't known yet) and a real count once the per-file processing loops
    start, since discovery already has to enumerate everything first.

    ``cancel_event`` -- optional cooperative-cancellation signal, checked at
    the same checkpoint granularity as progress reporting (every
    ``_PROGRESS_EVERY`` files). Raises :class:`IngestCancelled` when set;
    never leaves partial/corrupt Parquet behind, since ``_flush`` only
    writes once a full scenario bucket has been collected."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    report = IngestReport()

    # get_settings() guarantees output_raw_dir is set whenever it resolves at
    # all (see core/config.py). A bare Settings() built directly by a test/
    # script/per-source ingest (see config.py's settings_for_single_source)
    # may genuinely have output_raw_dir=None, e.g. when ingesting an *input*
    # source in isolation into its own cache slot -- guarded below the same
    # way input_raw_dir already is, so this function works for either domain
    # independently, not just "both or output-only".

    seen_scenarios: dict[str, dict] = {}
    seen_models: dict[str, dict] = {}

    # Group raw sources by scenario so we can ingest one scenario at a time and
    # flush its datasets before moving on (bounds peak memory). Multi-file
    # variables (e.g. all predation_* targets) are concatenated per scenario.
    # Each output scenario also carries its parent Ecopath model.
    output_by_scenario: dict[str, list[Path]] = defaultdict(list)
    output_model: dict[str, tuple[str, str]] = {}  # scenario_id -> (model_id, model_label)
    # scenario_id -> True when its files were found under 2+ distinct
    # directories -- Monte Carlo/Ecosampler, not one ordinary run (see
    # OutputRun.run_dirs). Only then does run_id get populated at all, so
    # an ordinary single-run scenario's rows/ids stay exactly as before
    # this existed.
    output_multi_run: dict[str, bool] = {}
    output_run_count: dict[str, int] = {}
    if settings.output_raw_dir is not None:
        for run in _discover_output(settings.output_raw_dir, on_progress, cancel_event):
            seen_models.setdefault(run.model_id, {"id": run.model_id, "name": run.model_label})
            seen_scenarios.setdefault(run.scenario_id, {
                "id": run.scenario_id, "label": run.scenario_label, "domain": "output",
                "model": run.model_id, "model_name": run.model_label,
            })
            output_model[run.scenario_id] = (run.model_id, run.model_label)
            output_by_scenario[run.scenario_id].extend(run.csv_paths)
            output_multi_run[run.scenario_id] = len(run.run_dirs) > 1
            output_run_count[run.scenario_id] = len(run.run_dirs)
        if any(output_multi_run.values()):
            report.has_multiple_runs = True
        if output_run_count:
            report.run_count = max(output_run_count.values())

    input_by_scenario: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    if settings.input_raw_dir is not None:
        for scenario_id, driver, trend_path in _discover_input(settings.input_raw_dir):
            seen_scenarios.setdefault(scenario_id, {
                "id": scenario_id, "label": scenario_id.upper(), "domain": "input",
                "model": None, "model_name": None,
            })
            input_by_scenario[scenario_id].append((driver, trend_path))

    output_total = sum(len(v) for v in output_by_scenario.values())
    done = 0
    for scenario_id, csv_paths in output_by_scenario.items():
        model_id, model_label = output_model[scenario_id]
        is_multi_run = output_multi_run.get(scenario_id, False)
        buckets: dict[tuple, list[pd.DataFrame]] = defaultdict(list)
        for csv_path in csv_paths:
            try:
                run_id = (
                    str(csv_path.parent.relative_to(settings.output_raw_dir))
                    if is_multi_run else None
                )
                meta, df = parse_ecosim_csv(
                    csv_path, scenario=scenario_id,
                    model=model_id, model_name=model_label, run_id=run_id,
                )
                report.files_read += 1
                if not df.empty:
                    buckets[(meta.variable, meta.freq)].append(df)
            except UnsupportedCsvShape:
                # Not a failure -- a recognised, known-unsupported shape
                # (Ecospace map-as-CSV / region-age-structure), see that
                # exception's docstring. Counted separately, never in
                # `errors`, same spirit as files skipped for lacking an
                # EcosimScenario header at all during discovery.
                report.skipped_unsupported += 1
            except OSError as exc:
                report.errors.append(describe_read_error(exc, csv_path, settings.output_raw_dir))
            except Exception as exc:  # noqa: BLE001 - collect and continue
                report.errors.append(f"{csv_path.name}: {exc}")
            done += 1
            if done % _PROGRESS_EVERY == 0:
                if on_progress is not None:
                    on_progress("output", done, output_total)
                if cancel_event is not None and cancel_event.is_set():
                    raise IngestCancelled()
        _flush(buckets, settings, report)
    if on_progress is not None and output_total:
        on_progress("output", output_total, output_total)

    input_total = sum(len(v) for v in input_by_scenario.values())
    done = 0
    for scenario_id, drivers in input_by_scenario.items():
        buckets = defaultdict(list)
        for driver, trend_path in drivers:
            try:
                df = parse_trend_csv(trend_path, scenario=scenario_id, variable=driver)
                report.files_read += 1
                if not df.empty:
                    buckets[(slugify(driver), "annual")].append(df)
            except OSError as exc:
                report.errors.append(describe_read_error(exc, trend_path, settings.input_raw_dir))
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{trend_path.name}: {exc}")
            done += 1
            if done % _PROGRESS_EVERY == 0:
                if on_progress is not None:
                    on_progress("input", done, input_total)
                if cancel_event is not None and cancel_event.is_set():
                    raise IngestCancelled()
        _flush(buckets, settings, report)
    if on_progress is not None and input_total:
        on_progress("input", input_total, input_total)

    report.scenarios = list(seen_scenarios.values())
    report.models = list(seen_models.values())
    _export_scenarios(report.scenarios, settings.dictionaries_dir)
    _export_models(report.models, settings.dictionaries_dir)

    # Deliberately does NOT build the catalog here any more (2026-08-28): this
    # function now ingests exactly one source in isolation into its own cache
    # slot (see config.py's settings_for_single_source) -- the catalog is a
    # COMBINED view over whichever source(s) are currently active, built once
    # by the caller (ingestion.activation's combine_and_rebuild) after this
    # returns, not per-source. Callers that used to rely on this doing it
    # implicitly (cli.py's bare `ecosim ingest`) now call build_catalog
    # themselves.
    return report


def _flush(buckets: dict[tuple, list[pd.DataFrame]], settings: Settings, report: IngestReport) -> None:
    """Concatenate and write each accumulated (variable, freq) dataset, then drop it."""
    for frames in buckets.values():
        combined = pd.concat(frames, ignore_index=True)
        write_dataset(combined, settings.timeseries_dir)
        report.datasets_written += 1
        report.rows_written += len(combined)
    buckets.clear()


def _export_scenarios(scenarios: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(scenarios).to_csv(out_dir / "scenarios.csv", index=False)


def _export_models(models: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = ["id", "name"]
    df = pd.DataFrame(models, columns=cols) if models else pd.DataFrame(columns=cols)
    df.to_csv(out_dir / "models.csv", index=False)
