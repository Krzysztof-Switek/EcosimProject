"""Which EwE model -- Ecopath, Ecosim, Ecospace -- a data source's files come
from. Shown on the start screen's tiles, since what can be analysed next
depends on it.

**Output** (verified on real exports, 2026-10-29, EwE 6.7): every file EwE
writes starts with nested ``"<HEADER x/>"`` blocks naming the model layers
that produced it, so the deepest block present is the file's origin:

* ``ecopath`` only            -> Ecopath output (``basic_estimates.csv``,
  ``ecopath_stats.csv``, ``biodiv_ind_Ecopath.csv``)
* ``ecopath`` + ``ecosim``    -> Ecosim output (``catch_annual.csv``, ...)
* ... + ``ecospace``          -> Ecospace output (``csv/EcospaceMap*.csv``,
  ``Ecospace RunInfo.txt``)

ESRI ASCII maps (``.asc``) carry no header; in an output folder they are
Ecospace's map output ("Ecospace is set to autosave ASCII output maps",
User Guide PDF p.65).

Page numbers here are the PDF's own page numbers (not the printed ones).

**Input** (from the manuals, docs/ewe-data-formats.md section 7):

* the model itself -- one database file, ``.ewemdb`` ("The model will be
  saved as a database with .ewemdb extension", PM PDF p.127), or the older
  Access form ``.eweaccdb`` that real output headers name as ``ModelSource``.
  It holds the Ecopath model with its Ecosim and Ecospace scenarios;
* Ecosim time series -- a CSV whose rows start ``Title``, optional
  ``Weight``, ``Pool code`` (and ``Pool code 2``), ``Type``, then one row per
  year (PM PDF p.270; type codes UG PDF p.80-81);
* Ecospace input layers -- ESRI ASCII rasters (``.asc``, UG PDF p.174), also
  ``.csv``/``.shp`` layers for import (UG PDF p.226, 240).

**Group names.** Most Ecosim outputs carry only EwE's group numbers
(``year\\group,1,2,...``). Ecopath's ``basic_estimates.csv`` lists them with
their names (``GroupNo,Group,B,PB,...`` -- verified on real exports,
2026-10-29), so identification also collects ``{number: name}`` per Ecopath
model. Numbers are per model (PM PDF p.270), hence keyed by ``ModelName``; a
model whose files disagree on a name is listed in ``group_conflicts`` and
gets none (a wrong name is worse than a number).

**Baseline biomass.** The same table's ``B`` column is each group's Ecopath
biomass -- the state Ecosim starts from ("key initial parameters inherited
from the base Ecopath model", PM PDF p.122; verified: Ecosim's first year
equals it, e.g. 0.33 vs 0.3299918). Collected per model the same way; a model
whose files disagree (e.g. Monte Carlo samples drawing B anew) is listed in
``baseline_conflicts`` and gets no baseline -- which run's B would apply?

Only file headers are read (the first few KB) -- whole files only for the
small Ecopath group tables; files that are only in the cloud (OneDrive
"Files On-Demand") are counted as not checked rather than downloaded --
reading one would download it.
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path

from ecosim.ingestion.file_access import is_cloud_only

# Bumped when identify() learns to record something new, so sources
# identified by an older version are identified again (start screen /
# app startup) -- 2: Ecopath group names, 3: Ecopath baseline biomass.
IDENTIFY_VERSION = 3
_HEADER_BYTES = 4096
_MAX_NAMES = 20  # model/scenario names kept per layer -- enough to show, bounded for huge sources
_MODEL_DB_SUFFIXES = (".ewemdb", ".eweaccdb")
_TIMESERIES_ROW_LABELS = {"title", "weight", "pool code", "pool code 2", "type"}


def _read_head(path: Path) -> str | None:
    try:
        with path.open("rb") as fh:
            return fh.read(_HEADER_BYTES).decode("utf-8-sig", errors="replace")
    except OSError:
        return None


def _rows(text: str) -> list[list[str]]:
    # The last line may be cut mid-way by the byte limit; csv copes, and only
    # the header block (always at the top) matters here.
    return [row for row in csv.reader(io.StringIO(text)) if row]


def ewe_header(text: str) -> tuple[list[str], dict[str, str]] | None:
    """The ``"<HEADER x/>"`` blocks in a file's head, in order (e.g.
    ``["software", "ecopath", "ecosim"]``), and their key/value fields --
    None if the file has no EwE header."""
    blocks: list[str] = []
    fields: dict[str, str] = {}
    for row in _rows(text):
        first = row[0].strip()
        if first.startswith("<HEADER") and first.endswith("/>"):
            name = first[len("<HEADER"):-2].strip()
            if name == "end":
                break
            blocks.append(name)
        elif blocks and len(row) >= 2:
            fields[first] = row[1].strip()
    return (blocks, fields) if blocks else None


def output_layer(blocks: list[str]) -> str | None:
    """The model layer an EwE output file comes from: the deepest of its header blocks."""
    for layer in ("ecospace", "ecosim", "ecopath"):
        if layer in blocks:
            return layer
    return None


def is_timeseries_input(text: str) -> bool:
    """An Ecosim time-series CSV (the input EwE reads for fitting and
    forcing): first row ``Title``, then labelled rows incl. ``Type`` before
    the yearly data (PM PDF p.270)."""
    rows = _rows(text)
    if not rows or rows[0][0].strip().lower() != "title":
        return False
    labels = [r[0].strip().lower() for r in rows[1:6]]
    return "type" in labels and all(
        lab in _TIMESERIES_ROW_LABELS or lab.lstrip("-").isdigit() for lab in labels
    )


def ecopath_group_names(text: str) -> dict[str, str] | None:
    """``{group number: name}`` from an Ecopath table with ``GroupNo`` and
    ``Group`` columns (``basic_estimates.csv``), else None."""
    rows = _rows(text)
    head = next((i for i, r in enumerate(rows) if r[0].strip() == "GroupNo"), None)
    if head is None or len(rows[head]) < 2 or rows[head][1].strip() != "Group":
        return None
    names = {r[0].strip(): r[1].strip() for r in rows[head + 1:] if len(r) >= 2 and r[0].strip().isdigit()}
    return names or None


def ecopath_baseline_biomass(text: str) -> dict[str, float] | None:
    """``{group number: B}`` from the same Ecopath table's ``B`` column, else None."""
    rows = _rows(text)
    head = next((i for i, r in enumerate(rows) if r[0].strip() == "GroupNo"), None)
    if head is None:
        return None
    cols = [c.strip() for c in rows[head]]
    if "B" not in cols:
        return None
    col = cols.index("B")
    out: dict[str, float] = {}
    for r in rows[head + 1:]:
        if len(r) > col and r[0].strip().isdigit():
            try:
                out[r[0].strip()] = float(r[col])
            except ValueError:
                continue
    return out or None


def _merge_per_model(entry: dict, key: str, conflicts_key: str, model: str | None, values: dict) -> None:
    """Add one file's ``{group: value}`` for ``model`` under ``entry[key]``;
    a disagreement with another file of the same model drops the model into
    ``entry[conflicts_key]`` instead (it gets no values at all)."""
    if not model or model in entry.setdefault(conflicts_key, []):
        return
    known = entry.setdefault(key, {}).setdefault(model, {})
    if any(known.get(k, v) != v for k, v in values.items()):
        entry[key].pop(model)
        entry[conflicts_key].append(model)
        return
    known.update(values)


def _add_name(bucket: dict, key: str, value: str | None) -> None:
    if value and value not in bucket[key] and len(bucket[key]) < _MAX_NAMES:
        bucket[key].append(value)


def _walk(root: Path):
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            yield Path(dirpath) / name


def identify_output(root: Path) -> dict:
    """Which models an output folder holds, from the files' own EwE headers.

    ``{"ecopath": {files, models}, "ecosim": {files, models, scenarios},
    "ecospace": {files, maps, models, scenarios}, "not_checked": n}`` --
    a layer is absent when no file came from it."""
    layers: dict[str, dict] = {}
    not_checked = 0

    def layer(name: str) -> dict:
        return layers.setdefault(name, {"files": 0, "models": [], "scenarios": []})

    for path in _walk(root):
        suffix = path.suffix.lower()
        if suffix == ".asc":
            entry = layer("ecospace")
            entry["maps"] = entry.get("maps", 0) + 1
            entry["files"] += 1
            continue
        if suffix not in (".csv", ".txt"):
            continue
        if is_cloud_only(path):
            not_checked += 1
            continue
        text = _read_head(path)
        header = ewe_header(text) if text else None
        origin = output_layer(header[0]) if header else None
        if origin is None:
            continue
        blocks, fields = header
        entry = layer(origin)
        entry["files"] += 1
        _add_name(entry, "models", fields.get("ModelName"))
        _add_name(entry, "scenarios", fields.get("EcospaceScenario") if origin == "ecospace"
                  else fields.get("EcosimScenario") if origin == "ecosim" else None)
        if origin == "ecopath" and "GroupNo" in text:
            full = path.read_text(encoding="utf-8-sig", errors="replace")
            names = ecopath_group_names(full)
            if names:
                _merge_per_model(entry, "groups", "group_conflicts", fields.get("ModelName"), names)
            baseline = ecopath_baseline_biomass(full)
            if baseline:
                _merge_per_model(entry, "baseline_biomass", "baseline_conflicts", fields.get("ModelName"), baseline)
    for name, entry in layers.items():
        if name == "ecopath":
            entry.pop("scenarios")  # Ecopath has no scenarios
            for key in ("group_conflicts", "baseline_conflicts"):
                if not entry.get(key):
                    entry.pop(key, None)
    return {**layers, "not_checked": not_checked, "version": IDENTIFY_VERSION}


def identify_input(root: Path) -> dict:
    """Which kinds of model input a folder holds (see the module docstring):
    ``{"ecopath_model": {files, names}, "ecosim_timeseries": {files, series},
    "ecospace_maps": {files, shapefiles}, "driver_trends": {files},
    "not_checked": n}`` -- a kind is absent when none was found.
    ``driver_trends`` are the ``trend_*.csv`` files this app already loads as
    driver series (their EwE origin isn't documented, so they're not filed
    under a model)."""
    found: dict[str, dict] = {}
    not_checked = 0
    for path in _walk(root):
        suffix = path.suffix.lower()
        if suffix in _MODEL_DB_SUFFIXES:
            entry = found.setdefault("ecopath_model", {"files": 0, "names": []})
            entry["files"] += 1
            _add_name(entry, "names", path.name)
        elif suffix == ".asc":
            entry = found.setdefault("ecospace_maps", {"files": 0, "shapefiles": 0})
            entry["files"] += 1
        elif suffix == ".shp":
            entry = found.setdefault("ecospace_maps", {"files": 0, "shapefiles": 0})
            entry["shapefiles"] += 1
        elif suffix == ".csv":
            if path.name.lower().startswith("trend_"):
                found.setdefault("driver_trends", {"files": 0})["files"] += 1
                continue
            if is_cloud_only(path):
                not_checked += 1
                continue
            text = _read_head(path)
            if text and is_timeseries_input(text):
                entry = found.setdefault("ecosim_timeseries", {"files": 0, "series": 0})
                entry["files"] += 1
                # Columns after the label column, one per time series.
                entry["series"] += max(0, len(_rows(text)[0]) - 1)
    return {**found, "not_checked": not_checked, "version": IDENTIFY_VERSION}


def identify(root: Path, kind: str) -> dict:
    return identify_output(root) if kind == "output" else identify_input(root)


def refresh_identification(registry) -> None:
    """Identify every scanned source not yet identified by this version of
    ``identify`` (see ``IDENTIFY_VERSION``). Best-effort: a source that fails
    (e.g. its folder is offline) is skipped and tried again next time."""
    import logging

    log = logging.getLogger("ecosim.identify")
    for source in registry.list_sources():
        if source.status != "ok" or (source.models or {}).get("version") == IDENTIFY_VERSION:
            continue
        if not source.path.is_dir():
            continue
        try:
            registry.set_models(source.id, identify(source.path, source.kind))
            log.info("Identified models of %s", source.name)
        except Exception:  # noqa: BLE001 -- best-effort background work
            log.exception("Could not identify models of %s", source.name)


def has_recognised_input(root: Path) -> bool:
    """Existence check for registering an input folder: stops at the first
    file that is a recognised model input (model database, time-series CSV,
    map) -- see ``validate_input_root``."""
    for path in _walk(root):
        suffix = path.suffix.lower()
        if suffix in _MODEL_DB_SUFFIXES or suffix in (".asc", ".shp"):
            return True
        if suffix == ".csv" and not is_cloud_only(path):
            text = _read_head(path)
            if text and is_timeseries_input(text):
                return True
    return False
