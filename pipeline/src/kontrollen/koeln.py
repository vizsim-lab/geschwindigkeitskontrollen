# SPDX-License-Identifier: AGPL-3.0-or-later
"""Köln: Geschwindigkeitsüberwachung der Stadt (Open Data, offenedaten-koeln.de).

Je Datensatz (2017–2022, 2023, 2024, 2025, …) eine Datei mit **einem Verstoß je Zeile** und
Tabellen der Standorte je Dienststelle („Standorttabelle s01“ …). Laut Beschreibung:

- **Vorgänge:** Jahr; Monat; vorfallsdatum (`10119` = 1.1.2019 – Tag ohne führende Null);
  vorfallsuhrzeit (`   5` = 00:05, ` 335` = 03:35); kennz1 (Ortskürzel – ungenutzt);
  geschwindigkeit; ueberschreitung; fahrzeugart; dienststelle (= Standorttyp, `S-01`); standort.
- Enthalten sind die Geschwindigkeits- und Rotlichtfälle des Ordnungs- und Verkehrsdienstes, die
  Fälle der Polizei fehlen. **Rotlicht** (Dienststellen `K-…`) bleibt draußen.
- **Standorttabellen:** Standortkürzel, erlaubte Geschwindigkeit Pkw und Lkw, Stadtteil (zum Teil
  mit zwei Buchstaben davor: einem anderen Standortcode), Tatstraße mit Hausnummer, Fahrtrichtung.

Eine **Kontrolle** ist hier: alle Verstöße einer Messstelle an einem Tag. Gemessene Fahrzeuge
(auch die nicht zu schnellen) nennt Köln nicht – `messungen` bleibt leer, `alle_gezaehlt` ist
falsch, einen Anteil gibt es nicht. Uhrzeit und Dauer der Kontrolle bleiben leer: die Zeiten der
Verstöße sagen nicht, wann gemessen wurde.

Die Id einer Kontrolle: `K<Datum>-<Dienststelle>-<Standort>`, z. B. `K2019-01-01-S02-0039`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from kontrollen import namen, tabellen
from kontrollen.schema import in_schema

STUFE_KMH = 20  # wie Berlin: bis 20 / über 20 km/h

VORGANG = ["vorfallsdatum", "ueberschreitung", "dienststelle", "standort"]


@dataclass
class Bericht:
    dateien: list[dict] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)


# --- Dateien zuordnen ----------------------------------------------------------------------


def art(pfad: Path) -> str:
    """„vorgaenge“, „standorte“ oder „unbekannt“ – nach der Kopfzeile."""
    k = set(tabellen.kopf(pfad))
    if {"vorfallsdatum", "dienststelle", "standort"} <= k:
        return "vorgaenge"
    if any("stadtteil" in s for s in k) or any("tatstr" in s for s in k):
        return "standorte"
    return "unbekannt"


_TYP = re.compile(r"(?:^|[_\W])([sk])[-_ ]?(?:loc[-_ ]?)?(\d{2})(?:\D|$)", re.I)


def typ_aus_name(name: str) -> str | None:
    """ "…__Standorttabelle_s01.csv" -> "S-01", "s-loc-02_2.csv" -> "S-02", "k-loc-03" -> "K-03"."""
    teil = name.split("__")[-1]
    m = _TYP.search(teil)
    return f"{m.group(1).upper()}-{m.group(2)}" if m else None


def datensatz(pfad: Path) -> str:
    """Datensatz einer Datei (der Teil des Namens vor „__“, siehe fetch._dateiname)."""
    return pfad.name.split("__")[0]


# --- Standorte -----------------------------------------------------------------------------


def _spalte(df: pd.DataFrame, *teile: str) -> str | None:
    for t in teile:
        for c in df.columns:
            if t in c:
                return c
    return None


def lies_standorte(pfad: Path, typ: str) -> pd.DataFrame:
    """Standorttabelle -> je Standort: typ, standort, tempo (Pkw), tempo_lkw, stadtteil,
    adresse, richtung."""
    df = tabellen.lies(pfad)
    sp = {
        "standort": _spalte(df, "kuerzel", "standort", "sloc", "loc"),
        "tempo": _spalte(df, "pkw"),
        "tempo_lkw": _spalte(df, "lkw"),
        "stadtteil": _spalte(df, "stadtteil", "ortsteil"),
        "adresse": _spalte(df, "tatstr", "strasse", "str"),
        "richtung": _spalte(df, "richtung"),
    }
    if not sp["standort"] or not sp["adresse"]:
        raise ValueError(
            f"{pfad.name}: Standortkürzel oder Straße nicht erkannt ({list(df.columns)})"
        )
    out = pd.DataFrame({k: df[v] if v else "" for k, v in sp.items()})
    out["standort"] = pd.to_numeric(out["standort"].str.strip(), errors="coerce").astype("Int64")
    out = out[out["standort"].notna()]
    out["typ"] = typ
    return out.drop_duplicates(["typ", "standort"], keep="last")


# --- Vorgänge ------------------------------------------------------------------------------


def datum(v: pd.Series) -> pd.Series:
    """ "10119" -> "2019-01-01", "311219" -> "2019-12-31" (Tag ohne führende Null)."""
    s = v.str.strip().str.zfill(6)
    d = pd.to_datetime(s, format="%d%m%y", errors="coerce")
    return d.dt.strftime("%Y-%m-%d")


def verdichte(pfad: Path, bericht: Bericht) -> pd.DataFrame:
    """Vorgänge -> je Dienststelle, Standort und Tag: Zahl der Verstöße, davon über 20 km/h."""
    teile = []
    zeilen = rot = ohne = 0
    for df in tabellen.stuecke(pfad, VORGANG):
        zeilen += len(df)
        dienst = df["dienststelle"].str.strip().str.upper()
        ist_rot = dienst.str.startswith("K")
        rot += int(ist_rot.sum())
        df = df[~ist_rot]
        u = pd.to_numeric(df["ueberschreitung"].str.strip().str.replace(",", "."), errors="coerce")
        t = pd.DataFrame(
            {
                "typ": dienst[~ist_rot].str.replace(r"^([SK])-?0*(\d)$", r"\1-0\2", regex=True),
                "standort": pd.to_numeric(df["standort"].str.strip(), errors="coerce"),
                "datum": datum(df["vorfallsdatum"]),
                "ueber": u,
            }
        )
        weg = t["datum"].isna() | t["standort"].isna() | t["ueber"].isna()
        ohne += int(weg.sum())
        t = t[~weg]
        t["stufe2"] = t["ueber"] > STUFE_KMH
        teile.append(
            t.groupby(["typ", "standort", "datum"], as_index=False).agg(
                verstoesse=("ueber", "size"), stufe2=("stufe2", "sum"), max_ueber=("ueber", "max")
            )
        )
    agg = pd.concat(teile, ignore_index=True) if teile else pd.DataFrame()
    if len(agg):  # Stücke können einen Tag teilen
        agg = agg.groupby(["typ", "standort", "datum"], as_index=False).agg(
            verstoesse=("verstoesse", "sum"),
            stufe2=("stufe2", "sum"),
            max_ueber=("max_ueber", "max"),
        )
    bericht.dateien.append(
        {"datei": pfad.name, "zeilen": zeilen, "rotlicht": rot, "unlesbar": ohne, "tage": len(agg)}
    )
    return agg


# --- alles ---------------------------------------------------------------------------------


_HOEHE = re.compile(r"[,;]?\s*(?:in\s+)?H(?:ö|oe)he\s+(?:(?:Haus|Hs\.?|Nr\.?)\s*)?", re.I)
_GGUE = re.compile(
    r"[,;]?\s*(?:gg(?:ü|ue)\.?|gegen(?:ü|ue)ber)\s+(?:(?:Haus|Hs\.?|Nr\.?)\s*)?", re.I
)
_NUMMER_AM_ENDE = re.compile(
    r"^(?P<s>.*?\D)\s*(?P<n>\d{1,4}\s*[a-zA-Z]?(?:\s*[-/]\s*\d{1,4}\s*[a-zA-Z]?)?)\s*$"
)


def adresse(text: str) -> tuple[str, str | None, bool]:
    """ "Amsterdamer Str. 80-86" -> ("Amsterdamer Str.", "80", False);
    "Kieskaulerweg, ggü. Haus 65" -> ("Kieskaulerweg", "65", True);
    "Berrenrather Str., Höhe 179" -> ("Berrenrather Str.", "179", False)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    gegenueber = bool(_GGUE.search(s))
    s = _GGUE.sub(" ", _HOEHE.sub(" ", s)).strip(" ,;")
    m = _NUMMER_AM_ENDE.match(s)
    if not m:
        return s, None, gegenueber
    return m.group("s").strip(" ,;"), namen.nummer(m.group("n")).hausnummer, gegenueber


_CODE_VORN = re.compile(r"^[A-ZÄÖÜ]{2}\s+(?=\S)")


def stadtteil(text: str) -> str:
    """ "RO Rodenkirchen" -> "Rodenkirchen" (zwei Buchstaben davor = anderer Standortcode)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return _CODE_VORN.sub("", s)


def lies_alle(dateien: list[Path]) -> tuple[pd.DataFrame, dict]:
    """Alle Dateien der Kölner Datensätze -> Kontrollen im gemeinsamen Schema und ein Bericht."""
    bericht = Bericht()
    je_ds: dict[str, dict[str, list[Path]]] = {}
    for f in sorted(dateien):
        a = art(f)
        if a == "unbekannt":
            bericht.hinweise.append(f"{f.name}: weder Vorgänge noch Standorte")
            continue
        je_ds.setdefault(datensatz(f), {"vorgaenge": [], "standorte": []})[a].append(f)
    zeilen = []
    for ds, teile in je_ds.items():
        orte = []
        for f in teile["standorte"]:
            typ = typ_aus_name(f.name)
            if typ is None:
                bericht.hinweise.append(f"{f.name}: Standorttyp nicht im Namen")
                continue
            orte.append(lies_standorte(f, typ))
        orte_df = (
            pd.concat(orte, ignore_index=True)
            if orte
            else pd.DataFrame(columns=["typ", "standort"])
        )
        for f in teile["vorgaenge"]:
            agg = verdichte(f, bericht)
            if agg.empty:
                continue
            agg["standort"] = agg["standort"].astype("Int64")
            m = agg.merge(orte_df, on=["typ", "standort"], how="left")
            fehlt = m["adresse"].isna()
            if fehlt.any():
                bericht.hinweise.append(
                    f"{ds}: {int(fehlt.sum())} Kontrollen an Standorten ohne Standorttabelle"
                )
            for r in m.itertuples(index=False):
                zeilen.append(zeile(r, ds))
    df = in_schema(pd.DataFrame(zeilen)) if zeilen else in_schema(pd.DataFrame())
    return df, {"dateien": bericht.dateien, "hinweise": bericht.hinweise}


def zeile(r, quelle: str) -> dict:
    roh = r.adresse if isinstance(r.adresse, str) else ""
    strasse, hnr, geg = adresse(roh)
    tempo = (
        pd.to_numeric(str(r.tempo).strip(), errors="coerce") if isinstance(r.tempo, str) else None
    )
    ri = namen.richtung(r.richtung if isinstance(r.richtung, str) else "")
    n = int(r.verstoesse)
    s2 = int(r.stufe2)
    return {
        "id": f"K{r.datum}-{r.typ.replace('-', '')}-{int(r.standort):04d}",
        "stadt": "koeln",
        "quelle": quelle,
        "datum": r.datum,
        "strasse_roh": roh,
        "nr_roh": None,
        "lage_roh": None,
        "bezirk_roh": stadtteil(r.stadtteil) if isinstance(r.stadtteil, str) else None,
        "richtung_roh": r.richtung if isinstance(r.richtung, str) else None,
        "strasse": strasse or None,
        "hausnummer": hnr,
        "gegenueber": geg,
        "lage_art": "keine",
        "kompass": ri.kompass,
        "richtung_ziel": ri.ziel,
        "tempo": int(tempo) if tempo is not None and not pd.isna(tempo) and tempo > 0 else None,
        "messungen": None,
        "ueberschreitungen": n,
        "stufe1": n - s2,
        "stufe2": s2,
        "stufe_kmh": STUFE_KMH,
        "fahrverbote": None,
        "alle_gezaehlt": False,
    }
