# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pfade und Konfiguration.

Alles relativ zur Repo-Wurzel; `KONTROLLEN_DATA` biegt das Datenverzeichnis um (Tests) – und
mit ihm `docs`, damit ein Testlauf nicht die Übersicht im Repo überschreibt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Paths:
    root: Path
    pipeline: Path
    config: Path
    data: Path
    docs: Path

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def interim(self) -> Path:
        return self.data / "interim"

    @property
    def karte(self) -> Path:
        return self.data / "karte"

    def data_file(self, rel: str) -> Path:
        return self.data / rel

    def repo_file(self, rel: str) -> Path:
        return self.root / rel


def get_paths() -> Paths:
    pipeline = ROOT / "pipeline"
    umgebogen = os.environ.get("KONTROLLEN_DATA")
    data = Path(umgebogen) if umgebogen else pipeline / "data"
    docs = data / "docs" if umgebogen else ROOT / "docs"
    return Paths(root=ROOT, pipeline=pipeline, config=pipeline / "config", data=data, docs=docs)


@cache
def _lade(pfad: Path) -> dict:
    with pfad.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_yaml(name: str, paths: Paths | None = None) -> dict:
    paths = paths or get_paths()
    return _lade(paths.config / name)


def quellen(paths: Paths | None = None) -> dict:
    return load_yaml("sources.yaml", paths)


def stadt(code: str, paths: Paths | None = None) -> dict:
    return quellen(paths)["staedte"][code]
