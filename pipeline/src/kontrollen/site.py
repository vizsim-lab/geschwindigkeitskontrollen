# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kartendaten bauen: Messstellen, Kontrollen, Abschnitte, CSV-Download, Manifest.

Ausgaben in data/karte/ (im Git, die Karte liefert sie aus). Frontend-Vertrag: die Feldnamen
in `messstellen.json` und `kontrollen.json` (`felder`) und die Dateinamen in
`manifest.dateien` – wer sie ändert, zieht js/ und tests/web/ im selben Schritt mit.

- **Messstelle** = Kontrollen, die an (fast) derselben Stelle derselben Straße verortet sind
  (`BUENDEL_M`). Grobe Verortungen (nur die Straße) werden nie mit genauen gebündelt.
- **kontrollen.json** – eine Zeile je Kontrolle, nur Zahlen und Verweise in Nachschlagelisten;
  die Karte filtert und rechnet die Messstellen daraus selbst (Jahr, Tempo, Verortung).
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd
import shapely
from pyproj import Transformer

from kontrollen.config import Paths, quellen

BUENDEL_M = 25  # m: Kontrollen näher als das an derselben Straße sind eine Messstelle
GENAU = ("hausnummer", "abschnitt", "kreuzung", "anschlussstelle")
METHODEN = (*GENAU, "strasse")
TAG0 = date(2000, 1, 1)  # Datum als Tage seit diesem Tag (kompakt, im Browser zurückgerechnet)

FELDER_STELLE = ["id", "stadt", "lon", "lat", "strasse", "methode", "abschnitt", "osm_maxspeed"]
FELDER_KONTROLLE = [
    "stelle", "tag", "beginn", "dauer", "tempo", "messungen", "ueber", "stufe1", "stufe2",
    "fahrverbote", "alle", "richtung", "ort",
]  # fmt: skip


def baue(p: Paths) -> dict:
    df = pd.read_parquet(p.interim / "kontrollen.parquet")
    geo = pd.read_csv(p.data_file("geokodierung.csv"), dtype={"id": str})
    m = df.merge(geo, on="id", how="left")
    q = quellen(p)
    p.karte.mkdir(parents=True, exist_ok=True)

    stellen, stelle_von = messstellen(m, q)
    m["stelle"] = m["id"].map(stelle_von)

    richtungen = _liste(m.apply(_richtung_text, axis=1))
    orte = _liste(m.apply(_ort_text, axis=1))
    zeilen = []
    for r in m.itertuples(index=False):
        zeilen.append(
            [
                _int(r.stelle),
                (date.fromisoformat(r.datum) - TAG0).days if isinstance(r.datum, str) else None,
                _minuten(r.beginn),
                _int(r.dauer_min),
                _int(r.tempo),
                _int(r.messungen),
                _int(r.ueberschreitungen),
                _int(r.stufe1),
                _int(r.stufe2),
                _int(r.fahrverbote),
                1 if r.alle_gezaehlt is True else 0,
                richtungen["index"][_richtung_text(r._asdict())],
                orte["index"][_ort_text(r._asdict())],
            ]
        )
    staedte = sorted(m["stadt"].unique())
    stellen_json = {
        "felder": FELDER_STELLE,
        "staedte": staedte,
        "methoden": list(METHODEN),
        "zeilen": [
            [
                s["id"], staedte.index(s["stadt"]), s["lon"], s["lat"], s["strasse"],
                METHODEN.index(s["methode"]), s["abschnitt"], s["osm_maxspeed"],
            ]
            for s in stellen
        ],
    }  # fmt: skip
    kontrollen_json = {
        "felder": FELDER_KONTROLLE,
        "tag0": TAG0.isoformat(),
        "richtungen": richtungen["liste"],
        "orte": orte["liste"],
        "zeilen": zeilen,
    }
    _schreibe_json(p.karte / "messstellen.json", stellen_json)
    _schreibe_json(p.karte / "kontrollen.json", kontrollen_json)
    _schreibe_json(p.karte / "abschnitte.geojson", _abschnitte(stellen))
    _csv(m, p.karte / "kontrollen.csv")

    manifest = _manifest(p, q, m, stellen)
    _schreibe_json(p.karte / "manifest.json", manifest, eingerueckt=True)
    return {
        "kontrollen": int(len(m)),
        "messstellen": len(stellen),
        "ohne_lage": int(m["stelle"].isna().sum()),
        "dateien": manifest["dateien"],
    }


# --- Messstellen ---------------------------------------------------------------------------


def messstellen(m: pd.DataFrame, q: dict) -> tuple[list[dict], dict[str, int]]:
    """Verortete Kontrollen -> Messstellen (gierig gebündelt je Stadt, Straße und Genauigkeit)."""
    stellen: list[dict] = []
    stelle_von: dict[str, int] = {}
    v = m[m["geo_lon"].notna()].copy()
    for stadt, t in v.groupby("stadt", sort=True):
        hin = Transformer.from_crs("EPSG:4326", q["staedte"][stadt]["crs_m"], always_xy=True)
        x, y = hin.transform(t["geo_lon"].to_numpy(), t["geo_lat"].to_numpy())
        t = t.assign(_x=x, _y=y, _genau=t["geo_methode"].isin(GENAU))
        # Punkte mit den meisten Kontrollen zuerst – sie werden Mitte ihrer Messstelle
        punkte = (
            t.groupby(["geo_strasse", "_genau", "geo_lon", "geo_lat"], dropna=False)
            .agg(_x=("_x", "first"), _y=("_y", "first"), n=("id", "size"))
            .reset_index()
            .sort_values(["n", "geo_lon", "geo_lat"], ascending=[False, True, True])
        )
        gruppen: list[dict] = []
        zu: dict[tuple, int] = {}
        raster: dict[tuple, list[int]] = {}
        for pt in punkte.itertuples(index=False):
            zelle = (math.floor(pt._x / BUENDEL_M), math.floor(pt._y / BUENDEL_M))
            ziel = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for gi in raster.get((zelle[0] + dx, zelle[1] + dy), []):
                        g = gruppen[gi]
                        if g["strasse"] == pt.geo_strasse and g["genau"] == pt._genau:
                            if math.hypot(g["x"] - pt._x, g["y"] - pt._y) <= BUENDEL_M:
                                ziel = gi
                                break
                    if ziel is not None:
                        break
                if ziel is not None:
                    break
            if ziel is None:
                ziel = len(gruppen)
                gruppen.append(
                    {"strasse": pt.geo_strasse, "genau": pt._genau, "x": pt._x, "y": pt._y,
                     "lon": pt.geo_lon, "lat": pt.geo_lat}
                )  # fmt: skip
                raster.setdefault(zelle, []).append(ziel)
            zu[(pt.geo_strasse, pt._genau, pt.geo_lon, pt.geo_lat)] = ziel
        t["_g"] = [
            zu[(s, g, lo, la)]
            for s, g, lo, la in zip(
                t["geo_strasse"], t["_genau"], t["geo_lon"], t["geo_lat"], strict=True
            )
        ]
        for gi, tg in t.groupby("_g", sort=True):
            g = gruppen[gi]
            methode = _haeufigste(tg["geo_methode"], METHODEN)
            seg = tg["geo_abschnitt"].dropna()
            idx = len(stellen)
            stellen.append(
                {
                    "id": f"{stadt[0].upper()}{idx:05d}",
                    "stadt": stadt,
                    "lon": round(float(g["lon"]), 6),
                    "lat": round(float(g["lat"]), 6),
                    "strasse": g["strasse"] if isinstance(g["strasse"], str) else None,
                    "methode": methode,
                    "abschnitt": seg.value_counts().index[0] if len(seg) else None,
                    "osm_maxspeed": _haeufigste(tg["osm_maxspeed"].dropna(), None),
                }
            )
            for i in tg["id"]:
                stelle_von[i] = idx
    return stellen, stelle_von


def _haeufigste(s: pd.Series, reihenfolge):
    if s.empty:
        return None
    z = s.value_counts()
    if reihenfolge:  # bei Gleichstand die genauere Methode
        z = z.sort_index(key=lambda i: [reihenfolge.index(x) for x in i]).sort_values(
            ascending=False, kind="stable"
        )
    return z.index[0]


def _abschnitte(stellen: list[dict]) -> dict:
    feats = []
    for i, s in enumerate(stellen):
        if not s["abschnitt"]:
            continue
        g = shapely.from_wkt(s["abschnitt"])
        feats.append(
            {
                "type": "Feature",
                "properties": {"s": i},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[round(x, 6), round(y, 6)] for x, y in g.coords],
                },
            }
        )
    return {"type": "FeatureCollection", "features": feats}


# --- Texte für Popups ----------------------------------------------------------------------


def _get(r, k):
    v = r.get(k) if isinstance(r, dict) else getattr(r, k, None)
    return v if isinstance(v, str) and v.strip() else None


def _richtung_text(r) -> str:
    """Berlin "Nordwesten/Michael-Brüc", Aachen "Roermonder Straße" – wie geliefert."""
    return _get(r, "richtung_roh") or ""


def _ort_text(r) -> str:
    """Lage wie geliefert: "Nr. 423 · zwischen Am Seegraben u. Grauammerpfad"."""
    teile = []
    if _get(r, "stadt") == "berlin":
        nr = _get(r, "nr_roh")
        if nr:
            teile.append(f"Nr. {nr}")
        lage = _get(r, "lage_roh")
        if lage:
            teile.append(
                f"an {lage[1:].strip()}"
                if lage.startswith("/")
                else f"zw. {lage}"
                if " u. " in lage
                else lage
            )
    else:
        teile.append(_get(r, "strasse_roh") or "")
    return " · ".join(t for t in teile if t)


def _liste(werte: pd.Series) -> dict:
    liste = sorted(set(werte.fillna("")))
    return {"liste": liste, "index": {w: i for i, w in enumerate(liste)}}


# --- CSV und Manifest ----------------------------------------------------------------------

CSV_SPALTEN = {
    "id": "id",
    "stadt": "stadt",
    "datum": "datum",
    "beginn": "beginn",
    "dauer_min": "dauer_min",
    "strasse_roh": "strasse",
    "nr_roh": "nr",
    "lage_roh": "zwischen",
    "bezirk_roh": "bezirk",
    "richtung_roh": "richtung",
    "tempo": "tempo",
    "messungen": "messungen",
    "ueberschreitungen": "ueberschreitungen",
    "stufe1": "stufe1",
    "stufe2": "stufe2",
    "fahrverbote": "fahrverbote",
    "alle_gezaehlt": "alle_fahrzeuge_gezaehlt",
    "geo_lon": "lon",
    "geo_lat": "lat",
    "geo_methode": "verortung",
    "geo_gebiet": "suchgebiet",
    "geo_strasse": "osm_strasse",
    "geo_abschnitt_m": "abschnitt_m",
    "geo_abstand_adresse_m": "abstand_adresse_m",
    "geo_abstand_abschnitt_m": "abstand_hausnummer_abschnitt_m",
    "geo_hinweis": "hinweis",
    "stelle_id": "messstelle",
}


def _csv(m: pd.DataFrame, ziel: Path) -> None:
    t = m.copy()
    t["stelle_id"] = t["stelle"].map(lambda i: None if pd.isna(i) else f"{int(i)}")
    t = t[list(CSV_SPALTEN)].rename(columns=CSV_SPALTEN)
    t.sort_values(["stadt", "datum", "beginn"], inplace=True, kind="stable")
    t.to_csv(ziel, index=False, encoding="utf-8")


def _manifest(p: Paths, q: dict, m: pd.DataFrame, stellen: list[dict]) -> dict:
    val_pfad = p.data_file("geokodierung_validierung.json")
    validierung = json.loads(val_pfad.read_text(encoding="utf-8")) if val_pfad.exists() else {}
    res_pfad = p.pipeline / q["staedte"]["aachen"]["kontrollen"]["ressourcen"]
    aachen_res = json.loads(res_pfad.read_text(encoding="utf-8")) if res_pfad.exists() else {}
    staedte = {}
    for code, cfg in q["staedte"].items():
        t = m[m["stadt"] == code]
        k = cfg["kontrollen"]
        quelle = {
            "label": k["label"],
            "bereitsteller": k["bereitsteller"],
            "kurz": k["kurz"],
            "titel": k["titel"],
            "herkunft_url": k["herkunft_url"],
            "lizenz": k.get("lizenz"),
            "lizenz_hinweis": k.get("lizenz_hinweis"),
        }
        if code == "aachen" and aachen_res:
            lizenzen = sorted(
                {d.get("lizenz") for d in aachen_res.get("datensaetze", []) if d.get("lizenz")}
            )
            quelle["lizenz"] = " / ".join(lizenzen) or None
            quelle["datensaetze"] = [
                {"titel": d["titel"], "url": d.get("url"), "lizenz": d.get("lizenz")}
                for d in aachen_res.get("datensaetze", [])
            ]
            quelle["dateien"] = len(aachen_res.get("dateien", []))
        staedte[code] = {
            "label": cfg["label"],
            "start": cfg["start"],
            "kontrollen": int(len(t)),
            "messstellen": sum(1 for s in stellen if s["stadt"] == code),
            "zeitraum": [t["datum"].min(), t["datum"].max()] if len(t) else None,
            "jahre": sorted({int(d[:4]) for d in t["datum"].dropna()}),
            "stufen": ["bis 20 km/h", "über 20 km/h"]
            if code == "berlin"
            else ["bis 15 km/h", "über 15 km/h"],
            "hat_dauer": bool(t["dauer_min"].notna().any()),
            "hat_tempo": bool(t["tempo"].notna().any()),
            "anteil_alle_gezaehlt": round(float(t["alle_gezaehlt"].mean()), 3) if len(t) else None,
            "quelle": quelle,
            "verortung": validierung.get(code),
        }
    o = q["osm"]
    return {
        "stand": date.today().isoformat(),
        "dateien": {
            "messstellen": "messstellen.json",
            "kontrollen": "kontrollen.json",
            "abschnitte": "abschnitte.geojson",
            "csv": "kontrollen.csv",
        },
        "staedte": staedte,
        "osm": {
            "bereitsteller": o["bereitsteller"],
            "lizenz": o["lizenz"],
            "lizenz_url": o["lizenz_url"],
        },
        "karte": q["karte"],
        "methoden": list(METHODEN),
    }


def _schreibe_json(pfad: Path, obj, eingerueckt: bool = False) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=1 if eingerueckt else None,
                      separators=None if eingerueckt else (",", ":"))  # fmt: skip
    pfad.write_text(text + "\n", encoding="utf-8")


def _int(v):
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _minuten(hhmm) -> int | None:
    if not isinstance(hhmm, str) or ":" not in hhmm:
        return None
    h, mi = hhmm.split(":")[:2]
    return int(h) * 60 + int(mi)
