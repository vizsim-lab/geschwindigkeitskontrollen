# SPDX-License-Identifier: AGPL-3.0-or-later
"""Aachen: Geschwindigkeitskontrollen der Stadt Aachen (Open Data, eine Datei je Monat).

Die Dateien sind Excel (einige CSV), ihre Spalten haben sich über die Jahre verschoben. Gelesen
wird darum über die Kopfzeile: die erste Zeile, in der „Messplatz“ (oder ähnlich) und eine
Fahrzeugzahl stehen; die Spalten werden über Muster zugeordnet (`SPALTEN`). Was keinem Muster
folgt, meldet `lies_alle` als Hinweis, statt es stumm zu verwerfen.

Inhalt je Zeile (Stand 2020): Datum, Messplatz (Straße), Fahrtrichtung (Straße, auf die der
Verkehr zufährt), Fahrzeuge gesamt, Verstöße bis 15 km/h und über 15 km/h. Eine Dauer, eine
Uhrzeit und ein Tempolimit gibt es nicht – sie bleiben leer.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
from pathlib import Path

import pandas as pd

from kontrollen import namen
from kontrollen.schema import in_schema

# Zielspalte -> Muster für die Kopfzeile (klein, Umlaute ausgeschrieben, nur Buchstaben/Ziffern)
SPALTEN: dict[str, list[str]] = {
    "datum": [r"^datum", r"^tag$", r"messdatum"],
    "uhrzeit_von": [r"^(uhrzeit|zeit)?von", r"^beginn", r"^start"],
    "uhrzeit_bis": [r"^(uhrzeit|zeit)?bis$", r"^ende"],
    "messplatz": [r"^messplatz", r"^messort", r"^messstelle", r"^standort", r"^strasse", r"^ort$"],
    "hausnummer": [r"^(haus)?nr", r"^hausnummer"],
    "fahrtrichtung": [r"^fahrtrichtung", r"^richtung"],
    "tempo": [r"^zul", r"hoechstgeschw", r"^vzul", r"^limit", r"^tempo", r"^erlaubt"],
    "messungen": [
        r"fahrzeugegesamt",
        r"gemessen",
        r"^fahrzeuge",
        r"^anzahlfahrzeuge",
        r"^gesamt$",
        r"durchfahrten",
    ],
    "stufe1": [r"^bis15", r"bis15kmh", r"verwarn"],
    "stufe2": [r"^ueber15", r"ueber15kmh", r"bussgeld", r"anzeige"],
    "ueberschreitungen": [r"^verstoesse", r"ueberschreitungen", r"beanstandet", r"^verwertbar"],
    "fahrverbote": [r"fahrverbot"],
    "dauer": [r"messdauer", r"^dauer"],
}


def _norm(s) -> str:
    return namen.schluessel(str(s or ""))


def zuordnen(kopf: list) -> dict[str, int]:
    """Kopfzeile -> {Zielspalte: Index}. Jede Spalte höchstens einmal, erstes Muster gewinnt."""
    out: dict[str, int] = {}
    belegt: set[int] = set()
    normiert = [_norm(k) for k in kopf]
    for ziel, muster in SPALTEN.items():
        for m in muster:
            for i, n in enumerate(normiert):
                if i not in belegt and n and re.search(m, n):
                    out[ziel] = i
                    belegt.add(i)
                    break
            if ziel in out:
                break
    return out


def _zeilen(pfad: Path) -> list[list]:
    if pfad.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        blaetter = pd.read_excel(pfad, sheet_name=None, header=None, dtype=object)
        out = []
        for df in blaetter.values():
            out += df.where(df.notna(), None).values.tolist()
        return out
    roh = pfad.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = roh.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    # Trenner: der häufigste in den ersten Zeilen (der Sniffer scheitert an Titelzeilen)
    probe = text[:4000]
    trenner = max(";,\t", key=probe.count)
    return [list(r) for r in csv.reader(io.StringIO(text), delimiter=trenner)]


def lies_datei(pfad: Path) -> tuple[pd.DataFrame, list[str]]:
    """Eine Monatsdatei -> (Zeilen im Schema, Hinweise)."""
    zeilen = _zeilen(pfad)
    hinweise: list[str] = []
    kopf_i, spalten = None, {}
    for i, z in enumerate(zeilen[:30]):
        s = zuordnen(z)
        if "messplatz" in s and ("messungen" in s or "stufe1" in s):
            kopf_i, spalten = i, s
            break
    if kopf_i is None:
        return in_schema(pd.DataFrame()), [f"{pfad.name}: keine Kopfzeile erkannt"]
    kopf = zeilen[kopf_i]
    unbekannt = [
        str(k) for j, k in enumerate(kopf) if k not in (None, "") and j not in spalten.values()
    ]
    if unbekannt:
        hinweise.append(f"{pfad.name}: Spalten ohne Zuordnung: {unbekannt}")
    daten = []
    letztes_datum = None
    for j, z in enumerate(zeilen[kopf_i + 1 :], start=kopf_i + 2):

        def w(feld, z=z):
            i = spalten.get(feld)
            return z[i] if i is not None and i < len(z) else None

        platz = w("messplatz")
        if platz is None or not str(platz).strip():
            continue
        if re.match(r"(?i)^\s*(summe|gesamt|insgesamt)", str(platz)):
            continue
        datum = _datum(w("datum")) or letztes_datum  # verbundene Zellen: Datum nur oben
        letztes_datum = datum
        s1, s2 = _int(w("stufe1")), _int(w("stufe2"))
        ueber = _int(w("ueberschreitungen"))
        if ueber is None and (s1 is not None or s2 is not None):
            ueber = (s1 or 0) + (s2 or 0)
        mess = _int(w("messungen"))
        strasse, hnr = _strasse_und_nummer(str(platz), w("hausnummer"))
        lg = _lage(strasse)
        ri = str(w("fahrtrichtung") or "").strip() or None
        daten.append(
            {
                "id": "A" + hashlib.sha1(f"{pfad.name}:{j}".encode()).hexdigest()[:9],
                "stadt": "aachen",
                "quelle": pfad.name,
                "datum": datum,
                "beginn": _uhrzeit(w("uhrzeit_von")),
                "dauer_min": _dauer(w("uhrzeit_von"), w("uhrzeit_bis"), w("dauer")),
                "strasse_roh": str(platz).strip(),
                "nr_roh": str(w("hausnummer") or "").strip() or None,
                "lage_roh": None,
                "bezirk_roh": None,
                "richtung_roh": ri,
                "strasse": lg[0],
                "hausnummer": hnr,
                "gegenueber": False,
                "lage_art": lg[1],
                "quer1": lg[2],
                "quer2": lg[3],
                "kompass": None,
                "richtung_ziel": ri,
                "tempo": _int(w("tempo")),
                "messungen": mess,
                "ueberschreitungen": ueber,
                "stufe1": s1,
                "stufe2": s2,
                "fahrverbote": _int(w("fahrverbote")),
                "alle_gezaehlt": mess is not None and ueber is not None and mess > ueber,
            }
        )
    return in_schema(pd.DataFrame(daten)), hinweise


def lies_alle(dateien: list[Path]) -> tuple[pd.DataFrame, list[str]]:
    teile, hinweise = [], []
    for p in sorted(dateien):
        df, h = lies_datei(p)
        teile.append(df)
        hinweise += h
    df = pd.concat(teile, ignore_index=True) if teile else in_schema(pd.DataFrame())
    # dieselbe Kontrolle in zwei Dateien (Nachlieferung, XLSX und CSV) -> einmal
    schluessel = ["datum", "strasse_roh", "richtung_roh", "messungen", "ueberschreitungen"]
    vorher = len(df)
    df = df.drop_duplicates(subset=schluessel, keep="first").reset_index(drop=True)
    if vorher != len(df):
        hinweise.append(f"{vorher - len(df)} doppelte Zeilen entfernt")
    return df, hinweise


# --- Feld-Helfer ---------------------------------------------------------------------------

_HNR_AM_ENDE = re.compile(r"^(?P<s>.*?\D)\s+(?P<n>\d{1,4}\s*[a-zA-Z]?)$")


def _strasse_und_nummer(platz: str, nr) -> tuple[str, str | None]:
    s = re.sub(r"\s+", " ", platz).strip()
    if nr not in (None, "") and str(nr).strip():
        return s, namen.nummer(str(nr)).hausnummer
    m = _HNR_AM_ENDE.match(s)
    if m:
        return m.group("s").strip(" ,"), namen.nummer(m.group("n")).hausnummer
    return s, None


_QUER = re.compile(r"\s*(?:/|\bEcke\b|\bH[öo]he\b|\bzw\.?\b|\bzwischen\b)\s*", re.I)


def _lage(strasse: str) -> tuple[str, str, str | None, str | None]:
    """ "Trierer Straße / Höhe Haus 12" … -> (Hauptstraße, Art, Quer1, Quer2)."""
    teile = [t for t in _QUER.split(strasse) if t.strip()]
    if len(teile) == 1:
        return strasse, "keine", None, None
    haupt, rest = teile[0].strip(), [t.strip() for t in teile[1:]]
    zw = re.split(r"\s+(?:und|u\.)\s+", " ".join(rest))
    if len(zw) == 2:
        return haupt, "zwischen", zw[0], zw[1]
    return haupt, "kreuzung", rest[0], None


def _int(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) and not pd.isna(v):
        return int(round(v))
    s = str(v).strip().replace(".", "").replace(",", ".")
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def _datum(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        if isinstance(v, (dt.date, pd.Timestamp)):  # Excel-Datumszelle
            return pd.Timestamp(v).strftime("%Y-%m-%d")
        if isinstance(v, (int, float)):  # Excel-Seriennummer
            if not 20000 < float(v) < 80000:
                return None
            return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))).strftime("%Y-%m-%d")
        s = str(v).strip()
        iso = re.match(r"^\d{4}-\d{2}-\d{2}", s)  # "2020-06-02 00:00:00"
        ts = pd.to_datetime(s[:10] if iso else s, dayfirst=not iso, errors="coerce")
        return None if pd.isna(ts) else ts.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return None


def _uhrzeit(v) -> str | None:
    if v is None:
        return None
    m = re.search(r"(\d{1,2})[:.](\d{2})", str(v))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _dauer(von, bis, dauer) -> int | None:
    a, b = _uhrzeit(von), _uhrzeit(bis)
    if a and b:
        m = (int(b[:2]) * 60 + int(b[3:])) - (int(a[:2]) * 60 + int(a[3:]))
        return m if m > 0 else m + 1440
    if dauer is not None:
        m = re.match(r"^\s*(\d+)[:.](\d{2})", str(dauer))
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        z = _int(dauer)
        return z
    return None
