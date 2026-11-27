"""Mapping of output variables to EwE "Results Extractor" categories.

The category is a function of the variable's dimensionality (group / fleet /
partner) plus the two relational variable names (``predation`` / ``prey``), so
new variables get classified automatically without a per-variable table. This
is the single source of truth; the catalog stores it and the UI groups by it.
"""

from __future__ import annotations

# Canonical order + the box titles of the Results Extractor window (UG p.128,
# Figure 1).
CATEGORY_ORDER: list[tuple[str, str]] = [
    ("functional_groups", "Functional groups only"),
    ("predators_with_prey", "Predators with attached prey"),
    ("prey_with_predators", "Prey with attached predators"),
    ("fleets_only", "Fleets only"),
    ("fleets_with_prey", "Fleets with attached prey"),
    # Not a Results Extractor box: Ecospace's region age-structure tables.
    ("age_structure", "Age structure (Ecospace)"),
    ("fitting_stats", "Fitting statistics"),
    ("indicators", "Indicators"),
]

# What a box's selection window picks (UG p.129): its "parent" entities and, in
# an "attached" box, for each of them its partners -- "you first select which
# predators you are interested [in], and then for each predator you have
# selected, you select which prey". One selection applies to every checked
# variable of the box. Dimensions are timeseries columns: in predation_<prey>
# files the row's group is the prey and the partner its predator, in
# prey_<predator> files the group is the predator and the partner its prey
# (ingestion/parsers/ecosim_csv.py). Boxes not listed have no selection window.
CATEGORY_DIMS: dict[str, tuple[str, str | None]] = {
    "functional_groups": ("group", None),
    "predators_with_prey": ("group", "partner"),
    "prey_with_predators": ("group", "partner"),
    "fleets_only": ("fleet", None),
    "fleets_with_prey": ("fleet", "group"),
    # stanza group -> its ages in months (ingestion/parsers/age_structure_csv.py)
    "age_structure": ("group", "partner"),
}


def categorize(variable: str, n_groups: int, n_fleets: int, n_partners: int) -> str:
    """Return the category id for an output variable."""
    if variable.startswith("age_structure"):
        return "age_structure"
    if variable == "predation":
        return "prey_with_predators"
    if variable == "prey":
        return "predators_with_prey"
    if n_fleets > 0:
        return "fleets_with_prey" if n_groups > 0 else "fleets_only"
    if n_partners > 0:
        return "predators_with_prey"
    if n_groups > 0:
        return "functional_groups"
    return "indicators"


# Equivalent SQL CASE used by the catalog build. Operates on already-aggregated
# columns (n_groups/n_fleets/n_partners), so it carries no aggregate functions —
# keeps the rule defined in exactly one place. See build.py.
CATEGORY_SQL = """
CASE
    WHEN domain <> 'output' THEN NULL
    WHEN variable LIKE 'age_structure%' THEN 'age_structure'
    WHEN variable = 'predation' THEN 'prey_with_predators'
    WHEN variable = 'prey'      THEN 'predators_with_prey'
    WHEN n_fleets > 0 AND n_groups > 0 THEN 'fleets_with_prey'
    WHEN n_fleets > 0 THEN 'fleets_only'
    WHEN n_partners > 0 THEN 'predators_with_prey'
    WHEN n_groups > 0 THEN 'functional_groups'
    ELSE 'indicators'
END
"""
