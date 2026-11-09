# SPDX-License-Identifier: AGPL-3.0-or-later
"""CSV-Dateien der Open-Data-Portale lesen: Kodierung und Trennzeichen erkennen, Spaltennamen
vergleichbar machen, gzip mitlesen (so liegen große Dateien im Entwicklungsauszug).

Gelesen wird alles als Text (`dtype=str`); Zahlen und Daten wandeln die Leser der Städte selbst,
damit „ 335“ (03:35) oder „10119“ (1.1.2019) nicht als Zahl verloren gehen.
"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

KODIERUNGEN = ("utf-8-sig", "cp1252")


def _oeffne(pfad: Path):
    return gzip.open(pfad, "rb") if pfad.suffix == ".gz" else pfad.open("rb")


def _probe(pfad: Path, n: int = 1 << 16) -> bytes:
    with _oeffne(pfad) as f:
        return f.read(n)


def kodierung(pfad: Path) -> str:
    probe = _probe(pfad)
    try:
        probe.decode("utf-8")
        return "utf-8-sig"
    except UnicodeDecodeError as e:
        # am Ende der Probe abgeschnittenes Zeichen ist kein Fehler
        if e.start >= len(probe) - 3:
            return "utf-8-sig"
        return "cp1252"


def trenner(pfad: Path, enc: str | None = None) -> str:
    """Der häufigste Trenner in der Kopfzeile (der csv.Sniffer scheitert an Titelzeilen)."""
    text = _probe(pfad).decode(enc or kodierung(pfad), errors="replace")
    kopf = next((z for z in text.splitlines() if z.strip()), "")
    return max(";,\t|", key=kopf.count)


def norm(name: str) -> str:
    """Spaltenname -> Vergleichsform: „Erlaubte Geschw. PKW“ -> „erlaubtegeschwpkw“."""
    s = (
        str(name)
        .lower()
        .replace("ß", "ss")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
    )
    return re.sub(r"[^0-9a-z]+", "", s)


def kopf(pfad: Path) -> list[str]:
    """Die Kopfzeile, normalisiert (`norm`)."""
    enc = kodierung(pfad)
    t = _probe(pfad).decode(enc, errors="replace").lstrip("﻿")
    zeile = next((z for z in t.splitlines() if z.strip()), "")
    return [norm(x) for x in zeile.split(trenner(pfad, enc))]


def lies(pfad: Path, **kw) -> pd.DataFrame:
    """Ganze Datei als Text; Spaltennamen normalisiert."""
    enc = kodierung(pfad)
    df = pd.read_csv(
        pfad, sep=trenner(pfad, enc), encoding=enc, dtype=str, keep_default_na=False, **kw
    )
    df.columns = [norm(c) for c in df.columns]
    return df


def stuecke(pfad: Path, spalten: list[str], groesse: int = 500_000) -> Iterator[pd.DataFrame]:
    """Große Datei stückweise, nur die genannten (normalisierten) Spalten."""
    enc = kodierung(pfad)
    roh = kopf(pfad)
    fehlen = [s for s in spalten if s not in roh]
    if fehlen:
        raise ValueError(f"{pfad.name}: Spalten fehlen: {fehlen} (da: {roh})")
    idx = [roh.index(s) for s in spalten]
    for df in pd.read_csv(
        pfad,
        sep=trenner(pfad, enc),
        encoding=enc,
        dtype=str,
        keep_default_na=False,
        usecols=idx,
        chunksize=groesse,
    ):
        df.columns = [roh[i] for i in sorted(idx)]
        yield df[spalten]
