# SPDX-License-Identifier: AGPL-3.0-or-later
"""Berlin: die Tabellen-PDFs der Polizei (Anlagen zum IFG-Bescheid vom 09.12.2020).

Je Jahr eine Anlage (2017, 2018, 2019, 2020 bis 31.08.), gedruckte Tabellen mit 16 Spalten.
Gelesen werden die Zeichen samt Lage (pdfplumber) – keine Tabellenerkennung, die rät:

- **Spalten**: die senkrechten Linien im Tabellenkopf der ersten Seite (dünne gefüllte
  Rechtecke). Die Folgeseiten haben keine Linien, aber dasselbe Raster.
- **Zellen**: ein zusammenhängender Lauf im Inhaltsstrom (das nächste Zeichen beginnt, wo das
  vorige endet). Ein Lauf gehört zur Spalte, in der er beginnt: lange Texte laufen in leere
  Nachbarzellen hinein ("Charlottenburg-Wilmersdorf, Steglitz-Zehlendorf" über „Richtung“),
  Zahlen stehen rechtsbündig in ihrer Spalte.
- **Zeilen**: Läufe gleicher Höhe.
- **Werte**: "-" heißt keine Angabe, Zahlen mit Tausenderpunkt ("5.114"). Mehrtägige Messungen
  tragen Datum und Uhrzeit in „Beginn“ und „Ende“ ("21.05.19 11:57").

Gedrehte Zeichen (die schmalen Spaltenköpfe) zählen nur für den Kopf. Leere Seiten am Ende
(Anlage 4: Seiten 12–22) liefern nichts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pdfplumber

# Spaltenköpfe, wie sie in den Anlagen stehen (Reihenfolge = Spalten)
KOPF = [
    "Direktionsbereich", "Abschnittsbereich", "Straßenname", "Nr.", "zwischen",
    "Verwaltungsbezirk", "Richtung", "erlaubte Geschwindigkeit", "Datum", "Beginn", "Ende",
    "Messungen", "Überschreitungen", "bis 20 km/h", "über 20 km/h", "Fahrverbote",
]  # fmt: skip
ZAHLEN = KOPF[11:]

_DATUM = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2}|\d{4})$")
_ZEIT = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATUM_ZEIT = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2}|\d{4})\s+(\d{1,2}):(\d{2})$")
_ZAHL = re.compile(r"^(\d+|\d{1,3}(\.\d{3})+)$")


@dataclass
class Bericht:
    """Was beim Lesen aufgefallen ist – landet im Build-Bericht."""

    datei: str
    seiten: int = 0
    zeilen: int = 0
    uebersprungen: list[str] = field(default_factory=list)  # Zeilen ohne Datum (Kopf, Rest)
    geteilte_zellen: int = 0  # mehr als ein Lauf in einer Zelle
    farbig: list[str] = field(default_factory=list)  # rote Einträge (Nachträge, Stand) ...
    farbige_zeilen: int = 0  # ... und wie viele Zeilen welche tragen (Bedeutung unbekannt)
    fehler: list[str] = field(default_factory=list)  # Werte, die nicht zu lesen sind

    def als_dict(self) -> dict:
        return {
            "datei": self.datei,
            "seiten": self.seiten,
            "zeilen": self.zeilen,
            "uebersprungen": len(self.uebersprungen),
            "uebersprungen_beispiele": self.uebersprungen[:5],
            "geteilte_zellen": self.geteilte_zellen,
            "farbige_zeilen": self.farbige_zeilen,
            "farbig_beispiele": self.farbig[:10],
            "fehler": len(self.fehler),
            "fehler_beispiele": self.fehler[:10],
        }


@dataclass
class _Lauf:
    text: str
    x0: float
    x1: float
    top: float
    unten: float
    size: float
    farbig: bool


def kopfraster(seite) -> tuple[list[float], float]:
    """Spaltengrenzen (x der senkrechten Linien im Tabellenkopf, Mitte der dünnen Rechtecke)
    und die Unterkante des Kopfs. Breite Rechtecke (Markierungen im Text) zählen nicht."""
    linien = [r for r in seite.rects if r["x1"] - r["x0"] < 0.5 and r["bottom"] - r["top"] > 2]
    if len(linien) != len(KOPF) + 1:
        raise ValueError(f"{len(linien)} Spaltenlinien statt {len(KOPF) + 1} im Tabellenkopf")
    return sorted((r["x0"] + r["x1"]) / 2 for r in linien), max(r["bottom"] for r in linien)


def _spalte(grenzen: list[float], x: float) -> int | None:
    eps = 0.05
    for i in range(len(grenzen) - 1):
        if grenzen[i] - eps <= x < grenzen[i + 1] - eps:
            return i
    return None


def _kopf(seite, grenzen: list[float], unten: float) -> list[str]:
    """Spaltenköpfe (auch gedreht) – zum Abgleich mit KOPF."""
    texte = [""] * (len(grenzen) - 1)
    for c in seite.chars:
        if c["top"] <= unten:
            i = _spalte(grenzen, (c["x0"] + c["x1"]) / 2)
            if i is not None:
                texte[i] += c["text"]
    return [" ".join(t.split()) for t in texte]


def _laeufe(seite) -> list[_Lauf]:
    """Aufrechte Zeichen in Stromreihenfolge -> zusammenhängende Läufe."""
    out: list[_Lauf] = []
    cur: _Lauf | None = None
    for c in seite.chars:
        if not c["upright"]:
            continue
        tol = 0.15 * c["size"]
        if cur is not None and abs(c["top"] - cur.top) < tol and abs(c["x0"] - cur.x1) < tol:
            cur.text += c["text"]
            cur.x1 = c["x1"]
        else:
            farbe = c.get("non_stroking_color")
            farbig = bool(farbe) and any(float(v) > 0 for v in farbe)
            cur = _Lauf(c["text"], c["x0"], c["x1"], c["top"], c["bottom"], c["size"], farbig)
            out.append(cur)
    return out


def _zeilen_einer_seite(laeufe: list[_Lauf]) -> list[list[_Lauf]]:
    """Läufe nach Unterkante bündeln (Toleranz 0,4 Schriftgrößen). Unterkante, nicht
    Oberkante: Nachträge in größerer Schrift (Anlage 3, S. 1) stehen auf derselben Linie."""
    zeilen: list[list[_Lauf]] = []
    for lauf in sorted(laeufe, key=lambda lf: lf.unten):
        erster = zeilen[-1][0] if zeilen else None
        if erster and lauf.unten - erster.unten < 0.4 * min(lauf.size, erster.size):
            zeilen[-1].append(lauf)
        else:
            zeilen.append([lauf])
    return zeilen


def zeilen(pfad: Path, bericht: Bericht | None = None) -> list[dict]:
    """Alle Datenzeilen einer Anlage: dict mit den Spalten aus KOPF (Text, getrimmt),
    dazu "seite" und "zeile" (laufende Nummer in der Datei, ab 1)."""
    bericht = bericht or Bericht(pfad.name)
    out: list[dict] = []
    with pdfplumber.open(pfad) as pdf:
        erste = pdf.pages[0]
        grenzen, kopf_unten = kopfraster(erste)
        kopf = _kopf(erste, grenzen, kopf_unten)
        if kopf != KOPF:
            raise ValueError(f"{pfad.name}: unerwarteter Tabellenkopf {kopf}")
        for nr, seite in enumerate(pdf.pages, start=1):
            laeufe = _laeufe(seite)
            if not laeufe:
                continue
            bericht.seiten = nr
            if nr == 1:
                laeufe = [lf for lf in laeufe if lf.top > kopf_unten]
            for gruppe in _zeilen_einer_seite(laeufe):
                zellen: list[list[_Lauf]] = [[] for _ in KOPF]
                bericht.farbige_zeilen += any(lf.farbig for lf in gruppe)
                for lauf in gruppe:
                    i = _spalte(grenzen, lauf.x0)
                    if i is None:
                        bericht.fehler.append(f"S. {nr}: außerhalb der Tabelle {lauf.text!r}")
                        continue
                    zellen[i].append(lauf)
                    if lauf.farbig:
                        bericht.farbig.append(f"S. {nr}, {KOPF[i]}: {lauf.text.strip()}")
                werte = {}
                for name, z in zip(KOPF, zellen, strict=True):
                    if len(z) > 1:
                        bericht.geteilte_zellen += 1
                    z.sort(key=lambda lf: lf.x0)
                    werte[name] = " ".join(lf.text.strip() for lf in z).strip()
                if not (_DATUM.match(werte["Datum"]) or _DATUM_ZEIT.match(werte["Datum"])):
                    bericht.uebersprungen.append(
                        f"S. {nr}: " + " | ".join(v for v in werte.values() if v)
                    )
                    continue
                werte["seite"] = nr
                werte["zeile"] = len(out) + 1
                out.append(werte)
    bericht.zeilen = len(out)
    return out


# --- Werte -----------------------------------------------------------------------------------


def zahl(text: str) -> int | None:
    """ "5.114" -> 5114, "-"/"" -> None. Anderes ist ein Fehler (ValueError)."""
    t = (text or "").strip()
    if t in ("", "-"):
        return None
    if not _ZAHL.match(t):
        raise ValueError(f"keine Zahl: {text!r}")
    return int(t.replace(".", ""))


def _jahr(j: str) -> int:
    return int(j) + 2000 if len(j) == 2 else int(j)


def zeitraum(datum: str, beginn: str, ende: str) -> tuple[datetime, datetime | None]:
    """Beginn und Ende als Zeitpunkte.

    Üblich: Datum "01.01.2020", Beginn "9:30", Ende "11:30" – endet die Kontrolle vor ihrem
    Beginn, ging sie über Mitternacht. Mehrtägig: Beginn/Ende mit Datum ("21.05.19 11:57").
    """
    d = _DATUM.match(datum) or _DATUM_ZEIT.match(datum)
    if not d:
        raise ValueError(f"kein Datum: {datum!r}")
    tag = datetime(_jahr(d.group(3)), int(d.group(2)), int(d.group(1)))

    def punkt(text: str) -> tuple[datetime | None, bool]:
        """(Zeitpunkt, mit eigenem Datum)"""
        if m := _DATUM_ZEIT.match(text):
            dt = datetime(_jahr(m.group(3)), int(m.group(2)), int(m.group(1)))
            return dt + timedelta(hours=int(m.group(4)), minutes=int(m.group(5))), True
        if m := _ZEIT.match(text):
            return tag + timedelta(hours=int(m.group(1)), minutes=int(m.group(2))), False
        if text.strip() in ("", "-"):
            return None, False
        raise ValueError(f"keine Uhrzeit: {text!r}")

    b, _ = punkt(beginn)
    if b is None:  # Datum allein (mehrtägig steht die Zeit manchmal nur im Datum)
        dz = _DATUM_ZEIT.match(datum)
        b = punkt(datum)[0] if dz else tag
    e, mit_datum = punkt(ende)
    if e is not None and not mit_datum and e < b:
        e += timedelta(days=1)
    return b, e
