# SPDX-License-Identifier: AGPL-3.0-or-later
"""Köln: Geschwindigkeitsüberwachung der Stadt (Open Data, offenedaten-koeln.de).

Je Datensatz (2017–2022, 2023, 2024, 2025) eine Datei mit **einem Verstoß je Zeile** und je
Dienststelle eine Standorttabelle („Standorttabelle s02“ …).

- **Vorgänge:** vorfallsdatum (`10117` = 1.1.2017, Tag ohne führende Null; ab 2023 `010123`),
  vorfallsuhrzeit, kennz (Ortskürzel des Kennzeichens – ungenutzt), geschwindigkeit,
  ueberschreitung (nach Toleranzabzug), fahrzeugart, dienststelle, standort (Kürzel).
  Kopf und Auffüllung wechseln („vorfallsdatum “, „010124        “); einzelne Zeilen sind um
  ein Feld verrutscht – sie bleiben als unlesbar draußen.
- **Nur die mobilen Kontrollen kommen in die Karte.** Dienststelle S-02 misst mobil (an einem
  Standort im Median an sechs Tagen im Jahr). S-01 sind die festen Anlagen, K-04 die Anlagen
  an Kreuzungen (beide an über 300 Tagen im Jahr). 2017 fehlt die Dienststelle, 2018/19 führt
  S-01 einige Fälle an Standorten der mobilen Tabelle: dann entscheidet das Kürzel – steht es nur
  in der mobilen Tabelle (s02), nicht auch in der der festen Anlagen (s01), zählt der Fall als
  mobil. Dieselben Kürzel stehen in beiden Tabellen für verschiedene Orte (971–983: in s01 die
  Rheinbrücke der A 1, in s02 die Brühler Straße) – mit S-02 gilt immer s02.
- **Standorttabellen:** Kürzel; zulässige Geschwindigkeit Pkw (und Lkw); „Stadtteil Tatort“ (oft
  mit einem zweiten Code davor: „AA   Riehl“, „1682 Riehl“; an der Autobahn
  „R118 BAB 4, km 66,320“); „Tatstraße mit Hausnummer“; Fahrtrichtung. 2024/2025 ohne
  Kopfzeile und mit einer Kennziffer nach dem Kürzel. **2023 fehlt das Kürzel** (vorn steht die
  Kennziffer, `pruefe_kuerzel` erkennt das am Abgleich mit den anderen Jahren): diese Zeilen
  bekommen es aus den Tabellen der anderen Jahre, wenn derselbe Text dort genau ein Kürzel hat.
  Kürzel werden über die Jahre neu vergeben – gesucht wird darum immer in der Tabelle desselben
  Datensatzes.
- **Adressen** (`adresse`): Hausnummer aus „80-86“, „Haus Nr.“, „Hs.Nr.“, „ggü. 161“, „Höhe 179“;
  Laternen, Lichtmasten, Kilometer und Meter („Lat.Nr.106“, „L.21“, „L 489 0,29“, „20mtr.“)
  sind keine Hausnummern – dann gilt nur die Straße. „A/B“, „vor B“, „Höhe B“, „unter B“ ->
  Kreuzung mit B. Abkürzungen der älteren Tabellen („Ber.Gl.Str.“) übersetzt config/orte.yaml.

Eine **Kontrolle** ist hier: alle Verstöße eines Standorts an einem Tag. Gemessene Fahrzeuge
(auch die nicht zu schnellen) nennt Köln nicht – `messungen` bleibt leer, `alle_gezaehlt` ist
falsch, einen Anteil gibt es nicht. Uhrzeit und Dauer bleiben leer: die Zeiten der Verstöße sagen
nicht, wann gemessen wurde. Es fehlen die Kontrollen der Polizei.

Die Id einer Kontrolle: `K<Datum>-<Kürzel>`, z. B. `K2019-01-01-0101`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from kontrollen import namen, tabellen
from kontrollen.schema import in_schema

STUFE_KMH = 20  # wie Berlin: bis 20 / über 20 km/h
MOBIL = "S-02"
FEST = "S-01"

VORGANG = ["vorfallsdatum", "ueberschreitung", "dienststelle", "standort"]
FELDER = ("standort", "tempo", "ort1", "ort2", "richtung")
# ohne Kopfzeile (2024, 2025): Kürzel; Kennziffer; Pkw; Lkw; Stadtteil; Tatstraße; Richtung
OHNE_KOPF = {"standort": 0, "tempo": 2, "ort1": 4, "ort2": 5, "richtung": 6}


@dataclass
class Bericht:
    dateien: list[dict] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)


# --- Dateien zuordnen ----------------------------------------------------------------------


def art(pfad: Path) -> str:
    """„standorte“ (nach dem Namen – nicht jede Tabelle hat eine Kopfzeile), „vorgaenge“
    (nach der Kopfzeile) oder „unbekannt“."""
    if "standorttabelle" in tabellen.norm(pfad.name) or typ_aus_name(pfad.name):
        return "standorte"
    if {"vorfallsdatum", "dienststelle", "standort"} <= set(tabellen.kopf(pfad)):
        return "vorgaenge"
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


def _text(*teile: str) -> str:
    return " | ".join(" ".join(str(t or "").split()) for t in teile)


def lies_standorte(pfad: Path, typ: str) -> pd.DataFrame:
    """Standorttabelle -> je Zeile: standort (Kürzel, <NA> wenn unbekannt), tempo, ort1
    („Stadtteil Tatort“), ort2 („Tatstraße mit Hausnummer“), richtung, typ, text."""
    z = tabellen.zeilen(pfad)
    if not z:
        return pd.DataFrame(columns=[*FELDER, "typ", "text"])
    kopf = [tabellen.norm(x) for x in z[0]]
    if kopf[0].startswith("standort"):

        def such(*teile: str) -> int | None:
            for t in teile:
                for i, c in enumerate(kopf):
                    if t in c:
                        return i
            return None

        idx = {
            "standort": such("standortkuerzel", "standort"),
            "tempo": such("pkw"),
            "ort1": such("tadtteil", "ortsteil"),
            "ort2": such("tatstr"),
            "richtung": such("fahrtrichtung", "richtung"),
        }
        daten = z[1:]
    else:
        idx, daten = OHNE_KOPF, z
        probe = daten[0]
        if len(probe) <= max(idx.values()) or not probe[idx["tempo"]].strip().isdigit():
            raise ValueError(f"{pfad.name}: Aufbau ohne Kopfzeile nicht erkannt ({probe})")
    if idx["ort2"] is None:
        raise ValueError(f"{pfad.name}: Spalte „Tatstraße“ nicht erkannt ({z[0]})")
    df = pd.DataFrame(
        {
            k: [r[i].strip() if i is not None and i < len(r) else "" for r in daten]
            for k, i in idx.items()
        }
    )
    df = df[(df["ort1"] != "") | (df["ort2"] != "")].reset_index(drop=True)
    df["standort"] = pd.to_numeric(df["standort"], errors="coerce").astype("Int64")
    kuerzel = df["standort"].dropna()
    # 2023: an Stelle des Kürzels steht eine Kennziffer (0–7) – kein Kürzel
    if kuerzel.empty or kuerzel.duplicated().mean() > 0.5:
        df["standort"] = pd.array([pd.NA] * len(df), dtype="Int64")
    df["typ"] = typ
    df["text"] = [_text(a, b, c) for a, b, c in zip(df.ort1, df.ort2, df.richtung, strict=True)]
    return df


def pruefe_kuerzel(tabellen_: dict[tuple[str, str], pd.DataFrame], bericht: Bericht) -> None:
    """Steht derselbe Text in mehreren Tabellen eines Typs, nennt die Mehrheit sein Kürzel. Weicht
    eine Tabelle dabei meist ab, steht vorn kein Kürzel (2023: eine Kennziffer) – es wird leer."""
    je_text: dict[tuple[str, str], list[tuple[tuple[str, str], int]]] = {}
    for key, t in tabellen_.items():
        for s, k in zip(t["text"], t["standort"], strict=True):
            if not pd.isna(k):
                je_text.setdefault((key[1], s), []).append((key, int(k)))
    stimmen: dict[tuple[str, str], list[int]] = {}
    for liste in je_text.values():
        if len({key for key, _ in liste}) < 2:
            continue
        rang = Counter(i for _, i in liste).most_common()
        if len(rang) > 1 and rang[0][1] == rang[1][1]:
            continue  # Gleichstand: nichts zu entscheiden
        for key, i in liste:
            stimmen.setdefault(key, [0, 0])[0 if i == rang[0][0] else 1] += 1
    for (ds, typ), (ja, nein) in stimmen.items():
        if nein > ja:
            t = tabellen_[(ds, typ)]
            t["standort"] = pd.array([pd.NA] * len(t), dtype="Int64")
            bericht.hinweise.append(
                f"{ds} {typ}: vorn steht kein Kürzel ({nein} von {ja + nein} Zeilen weichen von "
                f"den anderen Jahren ab)"
            )


def ergaenze_kuerzel(tabellen_: dict[tuple[str, str], pd.DataFrame], bericht: Bericht) -> None:
    """Tabellen ohne Kürzel (2023): das Kürzel aus den Tabellen der anderen Datensätze desselben
    Typs, wenn derselbe Text dort genau ein Kürzel hat. Bekämen zwei Zeilen dasselbe Kürzel, bleibt
    es bei beiden leer (welche Zeile gemeint ist, wäre geraten)."""
    for (ds, typ), t in tabellen_.items():
        if t.empty or t["standort"].notna().any():
            continue
        kand: dict[str, set[int]] = {}
        for (ds2, typ2), u in tabellen_.items():
            if typ2 != typ or ds2 == ds:
                continue
            for s, k in zip(u["text"], u["standort"], strict=True):
                if not pd.isna(k):
                    kand.setdefault(s, set()).add(int(k))
        neu = pd.Series(
            [next(iter(kand[s])) if len(kand.get(s, ())) == 1 else None for s in t["text"]],
            dtype="Int64",
        )
        doppelt = neu.notna() & neu.duplicated(keep=False)
        neu[doppelt] = pd.NA
        t["standort"] = neu.values
        bericht.hinweise.append(
            f"{ds} {typ}: Tabelle ohne Kürzel – {int(neu.notna().sum())} von {len(t)} Zeilen über "
            f"den Text aus anderen Jahren zugeordnet"
            + (f", {int(doppelt.sum())} mehrdeutig" if doppelt.any() else "")
        )


# --- Vorgänge ------------------------------------------------------------------------------


def datum(v: pd.Series) -> pd.Series:
    """ "10119" -> "2019-01-01", "311219" -> "2019-12-31" (Tag ohne führende Null)."""
    s = v.str.strip().str.zfill(6)
    d = pd.to_datetime(s, format="%d%m%y", errors="coerce")
    return d.dt.strftime("%Y-%m-%d")


def verdichte(pfad: Path, mobil: set[int], fest_ids: set[int], bericht: Bericht) -> pd.DataFrame:
    """Vorgänge -> je Standort und Tag: Zahl der Verstöße, davon über 20 km/h – nur mobile.

    `mobil`: Kürzel der mobilen Tabelle (s02), `fest_ids`: die der festen Anlagen (s01). Ohne
    Dienststelle oder mit S-01 zählt ein Fall als mobil, wenn sein Kürzel nur in s02 steht."""
    nur_mobil = mobil - fest_ids
    teile = []
    z = {"zeilen": 0, "mobil": 0, "fest": 0, "kreuzung": 0, "unbekannt": 0, "unlesbar": 0}
    for df in tabellen.stuecke(pfad, VORGANG):
        z["zeilen"] += len(df)
        d = df["dienststelle"].str.strip().str.upper()
        sid = pd.to_numeric(df["standort"].str.strip(), errors="coerce")
        tag = datum(df["vorfallsdatum"])
        u = pd.to_numeric(df["ueberschreitung"].str.strip().str.replace(",", "."), errors="coerce")
        k = d.str.startswith("K")
        lesbar = tag.notna() & sid.notna() & u.notna() & (d.isin([MOBIL, FEST, ""]) | k)
        ohne_s02 = lesbar & d.isin([FEST, ""])  # S-01 oder ohne Dienststelle
        ist_mobil = lesbar & (d.eq(MOBIL) | (ohne_s02 & sid.isin(nur_mobil)))
        z["unlesbar"] += int((~lesbar).sum())
        z["kreuzung"] += int((lesbar & k).sum())
        z["mobil"] += int(ist_mobil.sum())
        # S-01/ohne Dienststelle an einer festen Anlage – oder an einem Kürzel, das keine Tabelle
        # kennt: beides bleibt draußen
        z["fest"] += int((ohne_s02 & ~ist_mobil & sid.isin(fest_ids | mobil)).sum())
        z["unbekannt"] += int((ohne_s02 & ~sid.isin(fest_ids | mobil)).sum())
        t = pd.DataFrame(
            {"standort": sid[ist_mobil], "datum": tag[ist_mobil], "ueber": u[ist_mobil]}
        )
        t["stufe2"] = t["ueber"] > STUFE_KMH
        teile.append(
            t.groupby(["standort", "datum"], as_index=False).agg(
                verstoesse=("ueber", "size"), stufe2=("stufe2", "sum")
            )
        )
    agg = pd.concat(teile, ignore_index=True) if teile else pd.DataFrame()
    if len(agg):  # Stücke können einen Tag teilen
        agg = agg.groupby(["standort", "datum"], as_index=False).agg(
            verstoesse=("verstoesse", "sum"), stufe2=("stufe2", "sum")
        )
        agg["standort"] = agg["standort"].astype("int64")
    bericht.dateien.append({"datei": pfad.name, **z, "kontrollen": len(agg)})
    return agg


# --- Ortsangaben ---------------------------------------------------------------------------

_CODE = re.compile(r"^[A-Z0-9]{2,4}\s+(?=\S)")
_BAB = re.compile(r"^(?:[A-Z0-9]{2,4}\s+)?BAB\s*A?\s*(\d{1,3})\b")


def stadtteil_feld(text: str | None) -> tuple[str | None, str | None]:
    """„Stadtteil Tatort“ -> (Stadtteil, Autobahn): "AA   Riehl" -> ("Riehl", None),
    "1682 Riehl" -> ("Riehl", None), "R118 BAB 4, km 66,320" -> (None, "A 4")."""
    s = " ".join(str(text or "").split())
    m = _BAB.match(s)
    if m:
        return None, f"A {int(m.group(1))}"
    s = _CODE.sub("", s)
    return (s or None), None


@dataclass(frozen=True)
class Adresse:
    """„Tatstraße mit Hausnummer“, gelesen."""

    strasse: str | None
    hausnummer: str | None = None
    gegenueber: bool = False
    quer: str | None = None  # Kreuzung: "Butzweiler Str./Rochusstr.", "Kreuzung L92"


_GG = r"(?:gegen(?:ü|ue)ber|gg(?:ü|ue)(?:ber|b)?|geg|gg)"  # ggü., ggüb., ggüber, geg., gg.
_FREI = r"(?![a-zäöüß])"  # Zusatz endet (kein Wortteil: „vorm“, „Mastweg“, „nachts“)
_LAT = r"(?:Laterne|Lat\.?(?![a-zäöüß])|Strommast|Mast|L\.?\s?(?=\d))"  # „L12“, „L.21“: Laterne
# wo der Straßenname endet: Komma oder Doppelpunkt, ein Zusatz (mit Leerzeichen davor oder direkt
# nach einem Punkt: „Friedr.-Schmidt-Str.ggü.Lat.56“), eine Laterne (auch „L489“: Landesstraße),
# eine Zahl, ein großgeschriebenes Wort nach „Str.“/„Straße“ („Frankfurter Str. S-Bahnbrücke“)
_ENDE = re.compile(
    r"\s*[,:]"
    r"|(?:\s+|(?<=\.))(?:(?:in\s+)?[Hh](?:ö|oe)he|i\.\s*H\.|" + _GG + r"\.?|vor|v\.|hinter|"
    r"nach|unter|neben|neb\.|bis|Haus(?:nr|Nr|nummer|r)?|Hs\.?|HS|Nr|NR|Kreuzung|Ecke|"
    r"Einm(?:ü|ue)ndung|Einf\.|Ausf\.|Einfahrt|Ausfahrt|Km|km)" + _FREI + r"|"
    r"(?:\s+|(?<=\.)|(?<=[a-zäöüß]))" + _LAT + r"|"
    r"(?<=[a-zäöüß])(?=Höhe\b)"  # „AgrippinauferHöhe“
    r"|(?<=[a-zäöüß.])\s*(?=\d)"
    r"|(?<=[Ss]tr\.)\s*(?=[A-ZÄÖÜ])|(?<=traße)\s+(?=[A-ZÄÖÜ])"
)
# Laternen-, Mast-, Kilometer- und Meterangaben sind keine Hausnummern
_LATERNE = re.compile(
    r"(?:" + _LAT + r"|[Kk]m)\s*(?:-?\s*Nr\.?)?\s*\d+(?:[.,]\d+)?"
    r"\s*[a-zA-Z]?(?:\s*[-/]\s*\d+(?:[.,]\d+)?[a-zA-Z]?)?"
    r"|\d+\s*(?:m|mtr|Meter|meter)\b\.?"  # „20mtr.vor Lat.238“
)
_LATERNE_VORN = re.compile(r"^(?:Laterne|Lat\.?|Mast)\s*(?:-?\s*Nr\.?)?\s*\d+\s*-\s*(?=\D)")
# Zusätze vor der Nummer: „ggü. 161“, „gegenüber 11“, „Höhe 179“, „vor Haus Nr. 149“
_ZUSATZ = re.compile(
    r"^(?:(?:in\s+)?[Hh](?:ö|oe)he|i\.\s*H\.|"
    + _GG
    + r"|vor|v\.|hinter|nach|bis|ab)\.?"
    + _FREI
    + r"\s*"
)
_NUMMER = r"(\d{1,4})(?!\d|[.,]\d)\s*([a-zA-Z](?![a-zA-Z.]))?"  # nicht „0,24“ (Kilometer)
_HAUS = re.compile(r"\b(?:Haus|Hs)\b\.?\s*-?\s*(?:(?:Nr|Nummer)\b\.?)?\s*" + _NUMMER, re.I)
_HAUSNR = re.compile(r"\bHaus(?:nr|nummer|r)\b\.?\s*" + _NUMMER, re.I)
_NR = re.compile(r"\bNr\b\.?\s*" + _NUMMER, re.I)
_VORN = re.compile(r"^" + _NUMMER)
_GGUE = re.compile(r"(?<![a-zäöüß])" + _GG + _FREI, re.I)
_QUER = re.compile(
    r"(?:Kreuzung|Ecke|Einm(?:ü|ue)ndung|vor|v\.|hinter|unter|[Hh](?:ö|oe)he|i\.\s*H\.)\s*"
    r"(?P<q>[A-ZÄÖÜ][^,]*)$"
)
_KEINE_QUER = re.compile(r"^(?:Haus|Hs|HS|Nr|NR|Lat|Laterne|Mast|Kita|Schule|L\d)", re.I)
_SCHRAEG = re.compile(r"^(?P<a>[^/\d]+?)\s*/\s*(?P<b>[A-ZÄÖÜ][^/\d]+)$")


def adresse(text: str | None) -> Adresse:
    """ "Amsterdamer Str. 80-86" -> Straße "Amsterdamer Str.", Nr. 80;
    "Kieskaulerweg ggü. Haus Nr.65" -> Nr. 65, gegenüber; "Melatengürtel, Laterne 85-77" -> nur
    Straße; "Butzweiler Str./Rochusstr." und "Militärring v.Bachemer Landstr" -> Kreuzung."""
    s = " ".join(str(text or "").split())
    s = _LATERNE_VORN.sub("", s)  # „Lat.139 - Neusser Landstr.379“
    if not s:
        return Adresse(None)
    m = _SCHRAEG.match(s)
    if m:
        return Adresse(m.group("a").strip(" .,"), quer=m.group("b").strip(" .,"))
    e = _ENDE.search(s)
    strasse, rest = (s[: e.start()], s[e.start() :]) if e else (s, "")
    strasse = strasse.strip(" ,;:-")
    rest = rest.strip(" ,;:")
    ohne_laterne = _LATERNE.sub(" ", rest).strip(" ,;-")
    vorn = ohne_laterne
    while z := _ZUSATZ.match(vorn):
        vorn = vorn[z.end() :]
    # die Nummer gleich nach den Zusätzen, sonst die erste nach „Haus“, „Hs.“ oder „Nr.“
    n = _VORN.search(vorn) or min(
        (x for x in (p.search(ohne_laterne) for p in (_HAUSNR, _HAUS, _NR)) if x),
        key=lambda x: x.start(),
        default=None,
    )
    nr = namen.nummer(n.group(1) + (n.group(2) or "")).hausnummer if n else None
    q = _QUER.search(rest) if nr is None else None
    quer = q.group("q").strip(" .,") if q and not _KEINE_QUER.match(q.group("q")) else None
    return Adresse(strasse or None, hausnummer=nr, gegenueber=bool(_GGUE.search(rest)), quer=quer)


_ZW = re.compile(r"^(?:zw\.|zwischen)\s*", re.I)


def autobahn_lage(text: str | None) -> namen.Lage:
    """ "zw. AS Klettenberg und AK West" -> zwischen ("AS Klettenberg", "AK West"); sonst ein Ort
    ("Rheinbrücke in Höhe Rheinauen")."""
    s = " ".join(str(text or "").split())
    return namen.lage(_ZW.sub("", s))


_FAHRTRICHTUNG = re.compile(r"^(?:in\s+)?(?:Fahrtrichtung|Fahrtr\.|FR\b|RF\b)\.?\s*", re.I)


def richtung(text: str | None) -> namen.Richtung:
    """ "in Fahrtrichtung stadtauswärts" -> Ziel "stadtauswärts"; "in Fahrtrichtung Süden" -> S."""
    s = " ".join(str(text or "").split())
    return namen.richtung(_FAHRTRICHTUNG.sub("", s))


# --- alles ---------------------------------------------------------------------------------


def lies_alle(dateien: list[Path]) -> tuple[pd.DataFrame, dict]:
    """Alle Dateien der Kölner Datensätze -> Kontrollen im gemeinsamen Schema und ein Bericht."""
    bericht = Bericht()
    vorgaenge: dict[str, list[Path]] = {}
    tabs: dict[tuple[str, str], pd.DataFrame] = {}
    for f in sorted(dateien):
        a = art(f)
        if a == "unbekannt":
            bericht.hinweise.append(f"{f.name}: weder Vorgänge noch Standorte")
        elif a == "vorgaenge":
            vorgaenge.setdefault(datensatz(f), []).append(f)
        else:
            typ = typ_aus_name(f.name)
            if typ is None:
                bericht.hinweise.append(f"{f.name}: Standorttyp nicht im Namen")
                continue
            tabs[(datensatz(f), typ)] = lies_standorte(f, typ)
    pruefe_kuerzel(tabs, bericht)
    ergaenze_kuerzel(tabs, bericht)
    zeilen = []
    for ds, liste in sorted(vorgaenge.items()):
        leer = pd.DataFrame(columns=[*FELDER, "typ", "text"])
        s02 = tabs.get((ds, MOBIL), leer)
        s01 = tabs.get((ds, FEST), leer)
        mobil = {int(k) for k in s02["standort"].dropna()}
        fest_ids = {int(k) for k in s01["standort"].dropna()}
        orte = s02.dropna(subset=["standort"]).drop_duplicates("standort", keep="last")
        orte = orte.assign(standort=orte["standort"].astype("int64")).set_index("standort")
        for f in liste:
            agg = verdichte(f, mobil, fest_ids, bericht)
            if agg.empty:
                continue
            m = agg.join(orte, on="standort")
            fehlt = m["text"].isna()
            if fehlt.any():
                bericht.hinweise.append(
                    f"{ds}: {int(fehlt.sum())} Kontrollen an "
                    f"{m.loc[fehlt, 'standort'].nunique()} Standorten ohne Eintrag in der "
                    f"Standorttabelle (ohne Lage)"
                )
            for r in m.itertuples(index=False):
                zeilen.append(zeile(r, ds))
    df = in_schema(pd.DataFrame(zeilen)) if zeilen else in_schema(pd.DataFrame())
    return df, {"dateien": bericht.dateien, "hinweise": bericht.hinweise}


def _feld(r, k: str) -> str:
    v = getattr(r, k, None)
    return v if isinstance(v, str) else ""


def zeile(r, quelle: str) -> dict:
    ort1, ort2, ri_roh = _feld(r, "ort1"), _feld(r, "ort2"), _feld(r, "richtung")
    teil, autobahn = stadtteil_feld(ort1)
    a = Adresse(None) if autobahn else adresse(ort2)
    lg = autobahn_lage(ort2) if autobahn else None
    if autobahn:
        lage_art = lg.art
        quer1 = lg.namen[0] if lg.art in ("zwischen", "kreuzung") else None
        quer2 = lg.namen[1] if lg.art == "zwischen" else None
        ort = lg.namen[0] if lg.art == "ort" else None
    else:
        lage_art = "kreuzung" if a.quer else "keine"
        quer1, quer2, ort = a.quer, None, None
    ri = richtung(ri_roh)
    tempo = pd.to_numeric(_feld(r, "tempo"), errors="coerce")
    n = int(r.verstoesse)
    s2 = int(r.stufe2)
    return {
        "id": f"K{r.datum}-{int(r.standort):04d}",
        "stadt": "koeln",
        "quelle": quelle,
        "datum": r.datum,
        "strasse_roh": ort2 or None,
        "nr_roh": None,
        "lage_roh": ort1 or None,
        "bezirk_roh": teil,
        "richtung_roh": ri_roh or None,
        "strasse": a.strasse if not autobahn else None,
        "hausnummer": a.hausnummer,
        "gegenueber": a.gegenueber,
        "lage_art": lage_art,
        "quer1": quer1,
        "quer2": quer2,
        "ort": ort,
        "autobahn": autobahn,
        "kompass": ri.kompass,
        "richtung_ziel": ri.ziel,
        "tempo": int(tempo) if not pd.isna(tempo) and tempo > 0 else None,
        "messungen": None,
        "ueberschreitungen": n,
        "stufe1": n - s2,
        "stufe2": s2,
        "stufe_kmh": STUFE_KMH,
        "fahrverbote": None,
        "alle_gezaehlt": False,
    }
