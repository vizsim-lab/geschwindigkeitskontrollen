# SPDX-License-Identifier: AGPL-3.0-or-later
"""Aachen: Geschwindigkeitskontrollen der Stadt Aachen (Open Data, eine Datei je Monat).

Was das Portal liefert (Stand Herbst 2026): je Jahr ein Datensatz, darin nur die **letzten drei
Monate** („In den vergangenen drei Monaten …“) – ältere Monate verschwinden. Im Katalog stehen
darum Oktober–Dezember 2020 bis 2025 und Januar–September 2026. Den Juni 2020 der alten Karte
gibt es dort nicht mehr; er wird aus deren HTML gelesen (`lies_folium`, 86 Kontrollen).

Formate, die vorkommen:

- 2020: Datum, Messplatz, (BA), Fahrtrichtung, Fahrzeuge gesamt, „bis 20 km/h“, „über 20 km/h“
  (Juni 2020: Grenze 15 km/h). „BA“ ist nicht erklärt und überall 0 – ignoriert.
- ab 2021: Datum, Messplatz, Fahrtrichtung, „Fahrzeuge gesamt“ (Zeilenumbruch in der Zelle),
  Verstöße – ohne Aufteilung.
- ab Oktober 2025 zusätzlich CSV mit langem Datum („Montag, 1. Dezember 2025“); die CSV vom
  Januar 2026 hat eine Million leere Zeilen. Gibt es zu einem Monat Excel, gilt Excel.

Gelesen wird über die Kopfzeile (`SPALTEN`); Spalten ohne Zuordnung meldet `lies_alle` als
Hinweis. Messplatz = Straße der Kontrolle, Fahrtrichtung = wohin der Verkehr fährt (eine Straße,
ein Ort wie „Innenstadt“, „Würselen“ oder „Niederlande“). Uhrzeit, Dauer und Tempolimit gibt es
nicht – sie bleiben leer.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import io
import re
from pathlib import Path

import pandas as pd

from kontrollen import namen
from kontrollen.schema import in_schema

# Zielspalte -> Muster für die Kopfzeile (Vergleichsform: klein, ohne Leerzeichen/Satzzeichen)
SPALTEN: dict[str, list[str]] = {
    "datum": [r"^datum", r"^tag$", r"messdatum"],
    "uhrzeit_von": [r"^(uhrzeit|zeit)von", r"^beginn", r"^start"],
    "uhrzeit_bis": [r"^(uhrzeit|zeit)bis", r"^ende"],
    "messplatz": [r"^messplatz", r"^messort", r"^messstelle", r"^standort", r"^strasse", r"^ort$"],
    "hausnummer": [r"^(haus)?nr", r"^hausnummer"],
    "fahrtrichtung": [r"^fahrtrichtung", r"^richtung"],
    "tempo": [r"^zul", r"hoechstgeschw", r"^vzul", r"^limit", r"^tempo", r"^erlaubt"],
    "messungen": [r"fahrzeugegesamt", r"gemessen", r"^fahrzeuge", r"^anzahlfahrzeuge", r"^gesamt$"],
    "stufe1": [r"^bis\d+(kmh)?$", r"verwarn"],
    "stufe2": [r"^ueber\d+(kmh)?$", r"bussgeld", r"anzeige"],
    "ueberschreitungen": [r"^verstoesse", r"ueberschreitungen", r"beanstandet", r"^verwertbar"],
    "fahrverbote": [r"fahrverbot"],
    "dauer": [r"messdauer", r"^dauer"],
}
IGNORIERT = {"ba", "wochentag", "anteilverstoesse"}  # bekannt, ohne Inhalt für die Karte

MONATE = {
    "januar": 1, "februar": 2, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
    "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}  # fmt: skip


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


def _leer(z: list) -> bool:
    return all(v is None or (isinstance(v, float) and pd.isna(v)) or not str(v).strip() for v in z)


def _zeilen(pfad: Path) -> list[list]:
    if pfad.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        blaetter = pd.read_excel(pfad, sheet_name=None, header=None, dtype=object)
        out = []
        for df in blaetter.values():
            out += [z for z in df.where(df.notna(), None).values.tolist() if not _leer(z)]
        return out
    roh = pfad.read_bytes()
    text = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = roh.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    # Trenner: der häufigste in den ersten Zeilen (der Sniffer scheitert an Titelzeilen)
    probe = text[:4000]
    trenner = max(";,\t", key=probe.count)
    return [z for z in csv.reader(io.StringIO(text), delimiter=trenner) if not _leer(z)]


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
        str(k)
        for j, k in enumerate(kopf)
        if k not in (None, "") and j not in spalten.values() and _norm(k) not in IGNORIERT
    ]
    if unbekannt:
        hinweise.append(f"{pfad.name}: Spalten ohne Zuordnung: {unbekannt}")
    grenze = None  # "bis 20 km/h" -> 20
    if "stufe1" in spalten:
        m = re.search(r"(\d+)", str(kopf[spalten["stufe1"]]))
        grenze = int(m.group(1)) if m else None
    return _als_schema(zeilen[kopf_i + 1 :], spalten, pfad.name, kopf_i + 2, grenze), hinweise


def _als_schema(zeilen, spalten, quelle: str, erste_zeile: int, grenze) -> pd.DataFrame:
    daten = []
    letztes_datum = None
    for j, z in enumerate(zeilen, start=erste_zeile):

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
        ri = re.sub(r"\s+", " ", str(w("fahrtrichtung") or "")).strip() or None
        daten.append(
            {
                "id": "A" + hashlib.sha1(f"{quelle}:{j}".encode()).hexdigest()[:9],
                "stadt": "aachen",
                "quelle": quelle,
                "datum": datum,
                "beginn": _uhrzeit(w("uhrzeit_von")),
                "dauer_min": _dauer(w("uhrzeit_von"), w("uhrzeit_bis"), w("dauer")),
                "strasse_roh": re.sub(r"\s+", " ", str(platz)).strip(),
                "nr_roh": str(w("hausnummer") or "").strip() or None,
                "richtung_roh": ri,
                "strasse": lg[0],
                "hausnummer": hnr,
                "gegenueber": False,
                "lage_art": lg[1],
                "quer1": lg[2],
                "quer2": lg[3],
                "richtung_ziel": ri,
                "tempo": _int(w("tempo")),
                "messungen": mess,
                "ueberschreitungen": ueber,
                "stufe1": s1,
                "stufe2": s2,
                "stufe_kmh": grenze if s1 is not None or s2 is not None else None,
                "fahrverbote": _int(w("fahrverbote")),
                "alle_gezaehlt": mess is not None and ueber is not None and mess > ueber,
            }
        )
    return in_schema(pd.DataFrame(daten))


_FOLIUM = re.compile(r"bindTooltip\(\s*`<div>(.*?)</div>`", re.S)
_FELD = re.compile(r"([^<>:]+?)\s*:\s*<b>(.*?)</b>")


def lies_folium(pfad: Path) -> tuple[pd.DataFrame, list[str]]:
    """Juni 2020 aus der alten Folium-Karte (vizsim/geschwindigkeitskontrollen): jede Kontrolle
    steht dort als Tooltip ("Datum: <b>2020-06-02</b><br>Messplatz: <b>…</b>…")."""
    text = pfad.read_text(encoding="utf-8")
    zeilen = []
    for tip in _FOLIUM.findall(text):
        felder = {html.unescape(k).strip(): html.unescape(v).strip() for k, v in _FELD.findall(tip)}
        zeilen.append(felder)
    if not zeilen:
        return in_schema(pd.DataFrame()), [f"{pfad.name}: keine Kontrollen gefunden"]
    kopf = list(zeilen[0])
    tabelle = [kopf] + [[z.get(k) for k in kopf] for z in zeilen]
    spalten = zuordnen(tabelle[0])
    m = re.search(r"(\d+)", str(kopf[spalten["stufe1"]])) if "stufe1" in spalten else None
    df = _als_schema(tabelle[1:], spalten, pfad.name, 1, int(m.group(1)) if m else None)
    return df, []


def lies_alle(dateien: list[Path], alt: Path | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Alle Monatsdateien (Excel vor CSV, damit beim Entdoppeln Excel gilt) + alte Karte."""
    teile, hinweise = [], []
    for p in sorted(dateien, key=lambda f: (f.suffix.lower() == ".csv", f.name)):
        df, h = lies_datei(p)
        teile.append(df)
        hinweise += h
    if alt is not None and alt.exists():
        df, h = lies_folium(alt)
        teile.append(df)
        hinweise += h
    teile = [t for t in teile if len(t)]
    df = pd.concat(teile, ignore_index=True) if teile else in_schema(pd.DataFrame())
    # dieselbe Kontrolle in zwei Dateien (Excel und CSV desselben Monats) -> einmal
    schluessel = ["datum", "strasse_roh", "richtung_roh", "messungen", "ueberschreitungen"]
    vorher = len(df)
    df = df.drop_duplicates(subset=schluessel, keep="first").reset_index(drop=True)
    if vorher != len(df):
        hinweise.append(f"{vorher - len(df)} doppelte Zeilen entfernt (Excel und CSV)")
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
    """ "Trierer Straße / Kalkbergstraße" … -> (Hauptstraße, Art, Quer1, Quer2)."""
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


_LANG = re.compile(r"(\d{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)\s+(\d{4})")


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
        lang = _LANG.search(s)  # "Montag, 1. Dezember 2025"
        if lang and namen.schluessel(lang.group(2)) in MONATE:
            d = dt.date(
                int(lang.group(3)), MONATE[namen.schluessel(lang.group(2))], int(lang.group(1))
            )
            return d.isoformat()
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
        return _int(dauer)
    return None
