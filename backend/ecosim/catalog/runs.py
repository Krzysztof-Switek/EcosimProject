"""Monte Carlo / Ecosampler runs of a scenario and how they are summarised.

Ecosampler "records samples -- alternate mass-balanced parameter sets ... from
the built-in Monte Carlo routine, and replays these samples through all of the
EwE modules" (UG p.180); each sample is written to its own ``Sample_N`` folder
and the first, with the base parameters, to ``Sample_baseline`` (UG p.50-51).
The manual shows such results as the model's prediction (a line) with "the 5th
and 95th percentiles obtained from Ecosampler-perturbed model outputs" as a band
(UG p.180, Fig. 10) -- the summary used here: ``value`` from the baseline run,
``p05``/``p95`` over the samples.

``run_id`` (the run's folder, relative to the source) is set only for a
scenario whose files came from 2+ run folders; ordinary output has none.
"""

from __future__ import annotations

import re

# A run's role, from its folder (Windows or POSIX separators).
RUN_KIND_SQL = r"""CASE
    WHEN run_id IS NULL THEN 'single'
    WHEN regexp_matches(run_id, '(^|[\\/])Sample_baseline([\\/]|$)') THEN 'baseline'
    WHEN regexp_matches(run_id, '(^|[\\/])Sample_[0-9]+([\\/]|$)') THEN 'sample'
    ELSE 'main'
END"""

_SAMPLE = re.compile(r"^Sample_(baseline|\d+)$")


def _parts(path: str) -> list[str]:
    return [p for p in re.split(r"[\\/]", path) if p and p != "."]


def run_roots(folders: set[str]) -> dict[str, str]:
    """Each folder a run's files were found in (relative to the source) -> the
    run it belongs to. One Ecosampler sample writes into several folders
    (``Sample_00001/ecosim_<scenario>``, ``Sample_00001/<Ecospace
    scenario>``, ``.../RegionAgeStructure``), all one run: the ``Sample_N``
    folder. A folder outside the samples but inside the folder holding them is
    the main run, that folder. Anything else stays its own run."""
    sample_parents: set[tuple[str, ...]] = set()
    for f in folders:
        ps = _parts(f)
        i = next((i for i, p in enumerate(ps) if _SAMPLE.match(p)), None)
        if i is not None:
            sample_parents.add(tuple(ps[:i]))
    out: dict[str, str] = {}
    for f in folders:
        ps = _parts(f)
        sep = "\\" if "\\" in f else "/"
        i = next((i for i, p in enumerate(ps) if _SAMPLE.match(p)), None)
        if i is not None:
            root = ps[: i + 1]
        else:
            parent = next((list(sp) for sp in sorted(sample_parents, key=len, reverse=True)
                           if tuple(ps[: len(sp)]) == sp), None)
            root = ps if parent is None else parent
        out[f] = sep.join(root) or "."
    return out


def run_label(run_id: str) -> str:
    """``Sample_00012`` / ``Sample_baseline``, or ``<folder> (main run)`` for a run
    outside the sample folders."""
    parts = _parts(run_id)
    for p in parts:
        if _SAMPLE.match(p):
            return p
    return f"{parts[-1]} (main run)" if parts else "Main run"
