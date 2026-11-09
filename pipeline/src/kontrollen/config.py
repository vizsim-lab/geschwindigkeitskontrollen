# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pfade und Konfiguration.

Alles relativ zur Repo-Wurzel; `KONTROLLEN_DATA` biegt nur das Datenverzeichnis um (Tests).
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
    data = Path(os.environ.get("KONTROLLEN_DATA", pipeline / "data"))
    return Paths(root=ROOT, pipeline=pipeline, config=pipeline / "config", data=data)


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
