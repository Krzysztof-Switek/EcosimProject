"""Mapping of output variables to EwE "Results Extractor" categories.

The category is a function of the variable's dimensionality (group / fleet /
partner) plus the two relational variable names (``predation`` / ``prey``), so
new variables get classified automatically without a per-variable table. This
is the single source of truth; the catalog stores it and the UI groups by it.
"""

from __future__ import annotations

# Canonical order + English labels (mirrors the Results Extractor layout).
CATEGORY_ORDER: list[tuple[str, str]] = [
    ("functional_groups", "Functional groups"),
    ("predators_with_prey", "Predators (with prey)"),
    ("prey_with_predators", "Prey (with predators)"),
    ("fleets_only", "Fleets"),
    ("fleets_with_prey", "Fleets (with prey)"),
    ("fitting_stats", "Fitting statistics"),
    ("indicators", "Indicators"),
]


def categorize(variable: str, n_groups: int, n_fleets: int, n_partners: int) -> str:
    """Return the category id for an output variable."""
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
    WHEN variable = 'predation' THEN 'prey_with_predators'
    WHEN variable = 'prey'      THEN 'predators_with_prey'
    WHEN n_fleets > 0 AND n_groups > 0 THEN 'fleets_with_prey'
    WHEN n_fleets > 0 THEN 'fleets_only'
    WHEN n_partners > 0 THEN 'predators_with_prey'
    WHEN n_groups > 0 THEN 'functional_groups'
    ELSE 'indicators'
END
"""
