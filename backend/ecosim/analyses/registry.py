"""Discovers R analysis plugins under ``rkit/analyses/<id>/analysis.yaml``.

Each plugin is a plain folder on disk (source-controlled) — adding an analysis
is "drop a folder in", not a code change. See docs/data-contract.md.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from ecosim.core.config import Settings


class ParamSpec(BaseModel):
    key: str
    type: str
    default: object = None
    label: str | None = None


class AnalysisSpec(BaseModel):
    id: str
    name: str
    description: str | None = None
    requires: dict = {}
    params: list[ParamSpec] = []
    entry: str
    dir: Path

    @property
    def entry_path(self) -> Path:
        return self.dir / self.entry

    def is_compatible(self, available_variables: set[str]) -> bool:
        """Whether this analysis' declared requirements are met by whatever
        variables a caller currently has selected (e.g. the time-series basket)."""
        required = set(self.requires.get("variables") or [])
        return required.issubset(available_variables)


def list_analyses(settings: Settings | None = None) -> list[AnalysisSpec]:
    # analyses_dir only depends on project_root, a compile-time constant --
    # not on any active data source -- so the R plugin catalog is browsable
    # even before a data source has ever been configured. A bare Settings()
    # (not get_settings()) resolves that without touching the workspace
    # registry at all.
    settings = settings or Settings()
    root = settings.analyses_dir
    if not root.exists():
        return []
    specs = []
    for yaml_path in sorted(root.glob("*/analysis.yaml")):
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        specs.append(AnalysisSpec(**raw, dir=yaml_path.parent))
    return specs


def get_analysis(analysis_id: str, settings: Settings | None = None) -> AnalysisSpec | None:
    for spec in list_analyses(settings):
        if spec.id == analysis_id:
            return spec
    return None
