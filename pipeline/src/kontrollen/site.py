# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kartendaten bauen: Messstellen, Kontrollen, Abschnitte, CSV-Download, Manifest.

Ausgaben in data/karte/ (im Git, die Karte liefert sie aus). Frontend-Vertrag: die Feldnamen
in `messstellen.json` und `kontrollen.json` (`felder`) und die Dateinamen in
`manifest.dateien` – wer sie ändert, zieht js/ und tests/web/ im selben Schritt mit.

- **Messstelle** = Kontrollen, die an (fast) derselben Stelle derselben Straße verortet sind
  (`BUENDEL_M`). Grobe Verortungen (nur die Straße) werden nie mit genauen gebündelt.
- **kontrollen.json** – eine Zeile je Kontrolle, nur Zahlen und Verweise in Nachschlagelisten;
  die Karte filtert und rechnet die Messstellen daraus selbst (Jahr, Tempo, Verortung).
- **datenlage.json** – je Stadt aus `datenlage` in sources.yaml ein Punkt mit Stand, Belegen und
  Anfragetext; dieselben Angaben als Übersicht in docs/DATENLAGE.md.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import shapely
from pyproj import Transformer

from kontrollen.config import Paths, quellen

BUENDEL_M = 25  # m: Kontrollen näher als das an derselben Straße sind eine Messstelle
GENAU = ("hausnummer", "abschnitt", "kreuzung", "anschlussstelle")
METHODEN = (*GENAU, "strasse")
TAG0 = date(2000, 1, 1)  # Datum als Tage seit diesem Tag (kompakt, im Browser zurückgerechnet)

FELDER_STELLE = [
    "id",
    "stadt",
    "lon",
    "lat",
    "strasse",
    "methode",
    "lage",
    "osm_maxspeed",
    "hinweis",
]
FELDER_KONTROLLE = [
    "stelle", "tag", "beginn", "dauer", "tempo", "messungen", "ueber", "stufe1", "stufe2",
    "fahrverbote", "alle", "richtung", "ort", "grenze",
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
                1 if r.alle_gezaehlt is not pd.NA and bool(r.alle_gezaehlt) else 0,
                richtungen["index"][_richtung_text(r._asdict())],
                orte["index"][_ort_text(r._asdict())],
                _int(r.stufe_kmh),
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
                METHODEN.index(s["methode"]), s["lage"], s["osm_maxspeed"], s["hinweis"],
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

    dl = datenlage(q, stellen, m)
    _schreibe_json(p.karte / "datenlage.json", dl, eingerueckt=True)
    manifest = _manifest(p, q, m, stellen)
    _schreibe_json(p.karte / "manifest.json", manifest, eingerueckt=True)
    doku = p.docs / "DATENLAGE.md"
    doku.parent.mkdir(parents=True, exist_ok=True)
    doku.write_text(datenlage_md(dl, manifest["stand"]), encoding="utf-8")
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
        t = t.assign(px=x, py=y, genau=t["geo_methode"].isin(GENAU))
        # Punkte mit den meisten Kontrollen zuerst – sie werden Mitte ihrer Messstelle
        punkte = (
            t.groupby(["geo_strasse", "genau", "geo_lon", "geo_lat"], dropna=False)
            .agg(px=("px", "first"), py=("py", "first"), n=("id", "size"))
            .reset_index()
            .sort_values(["n", "geo_lon", "geo_lat"], ascending=[False, True, True])
        )
        gruppen: list[dict] = []
        zu: dict[tuple, int] = {}
        raster: dict[tuple, list[int]] = {}
        for pt in punkte.itertuples(index=False):
            zelle = (math.floor(pt.px / BUENDEL_M), math.floor(pt.py / BUENDEL_M))
            ziel = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for gi in raster.get((zelle[0] + dx, zelle[1] + dy), []):
                        g = gruppen[gi]
                        if g["strasse"] == pt.geo_strasse and g["genau"] == pt.genau:
                            if math.hypot(g["x"] - pt.px, g["y"] - pt.py) <= BUENDEL_M:
                                ziel = gi
                                break
                    if ziel is not None:
                        break
                if ziel is not None:
                    break
            if ziel is None:
                ziel = len(gruppen)
                gruppen.append(
                    {"strasse": pt.geo_strasse, "genau": pt.genau, "x": pt.px, "y": pt.py,
                     "lon": pt.geo_lon, "lat": pt.geo_lat}
                )  # fmt: skip
                raster.setdefault(zelle, []).append(ziel)
            zu[(pt.geo_strasse, pt.genau, pt.geo_lon, pt.geo_lat)] = ziel
        t["_g"] = [
            zu[(s, g, lo, la)]
            for s, g, lo, la in zip(
                t["geo_strasse"], t["genau"], t["geo_lon"], t["geo_lat"], strict=True
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
                    "lage": _haeufigste(tg.apply(_ort_text, axis=1), None),
                    "hinweis": _haeufigste(tg["geo_hinweis"].dropna(), None),
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
        g = shapely.from_wkt(s["abschnitt"])  # Linie, bei „nur Straße“ auch mehrteilig
        teile = [x for x in getattr(g, "geoms", [g]) if x.geom_type == "LineString"]
        if not teile:
            continue
        koord = [[[round(x, 6), round(y, 6)] for x, y in t.coords] for t in teile]
        geom = (
            {"type": "LineString", "coordinates": koord[0]}
            if len(koord) == 1
            else {"type": "MultiLineString", "coordinates": koord}
        )
        feats.append(
            {
                "type": "Feature",
                "properties": {"s": i, "m": METHODEN.index(s["methode"])},
                "geometry": geom,
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
    "stufe_kmh": "stufen_grenze_kmh",
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
    t = t.sort_values(["stadt", "datum", "beginn"], kind="stable")
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
            "stufen": _stufen(t),
            "hat_dauer": bool(t["dauer_min"].notna().any()),
            "hat_fahrverbote": bool(t["fahrverbote"].notna().any()),
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
            "datenlage": "datenlage.json",
        },
        "datenlage_stand": STAND,
        "staedte": staedte,
        "osm": {
            "bereitsteller": o["bereitsteller"],
            "lizenz": o["lizenz"],
            "lizenz_url": o["lizenz_url"],
        },
        "karte": q["karte"],
        "methoden": list(METHODEN),
    }


# --- Datenlage -----------------------------------------------------------------------------

STAND = {
    "in_karte": "in der Karte",
    "offen": "offen, noch nicht in der Karte",
    "geliefert": "auf Anfrage herausgegeben",
    "kandidat": "erhoben – Anfrage aussichtsreich",
    "teilweise": "nur Summen, Standorte oder Planungen offen",
    "abgelehnt": "Anfrage gescheitert",
}
FDS_SUCHE = "https://fragdenstaat.de/behoerden/?q="


def anfrage(vorlage: dict, e: dict) -> dict:
    """Anfragetext aus `anfrage_vorlage` (Feld „Anfrage“ auf FragDenStaat) für einen Eintrag."""
    zusatz = " ".join((e.get("anfrage_zusatz") or "").split())
    text = vorlage["text"].format(
        stelle=e.get("stelle") or f"die Stadt {e['kommune']}",
        seit=e.get("seit") or "dem 1. Januar 2019",
        zusatz=f"\n{zusatz}\n" if zusatz else "",
    )
    return {"betreff": vorlage["betreff"], "text": text.strip()}


def kontakt(roh: dict | None) -> dict | None:
    """Kontakt über die Behördensuche von FragDenStaat (keine Namen, keine Adressen)."""
    if not roh:
        return None
    out = {k: roh[k] for k in ("name", "fds") if roh.get(k)}
    if roh.get("fds_suche"):
        out["fds"] = FDS_SUCHE + quote_plus(roh["fds_suche"])
        out["fds_suche"] = True
    return out or None


def datenlage(q: dict, stellen: list[dict], m: pd.DataFrame) -> dict:
    """Einträge `datenlage` aus sources.yaml -> GeoJSON (ein Punkt je Stadt).

    Liegt eine Stadt in der Karte (`stadt:`), kommt ihr Punkt aus der Mitte (Median) ihrer
    Messstellen und die Zahl der Kontrollen aus den Daten; ohne Kontrollen fällt der Eintrag
    weg, damit die Karte nichts „in der Karte“ nennt, was fehlt."""
    vorlage, recht = q["anfrage_vorlage"], q.get("recht", {})
    features = []
    for e in q.get("datenlage", []):
        if e["stand"] not in STAND:
            raise ValueError(f"Datenlage {e['kommune']}: Stand {e['stand']!r} unbekannt")
        lon, lat, n = e.get("lon"), e.get("lat"), None
        if e.get("stadt"):
            if e["stadt"] not in q["staedte"]:
                raise ValueError(f"Datenlage {e['kommune']}: Stadt {e['stadt']!r} fehlt in staedte")
            st = [s for s in stellen if s["stadt"] == e["stadt"]]
            if not st:
                continue
            lon = round(sorted(s["lon"] for s in st)[len(st) // 2], 5)
            lat = round(sorted(s["lat"] for s in st)[len(st) // 2], 5)
            n = int((m["stadt"] == e["stadt"]).sum())
        if lon is None or lat is None:
            raise ValueError(f"Datenlage {e['kommune']}: lon/lat fehlen")
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "kommune": e["kommune"],
                    "land": e.get("land"),
                    "stand": e["stand"],
                    "stadt": e.get("stadt"),
                    "kontrollen": n,
                    "was": e.get("was"),
                    "situation": e.get("situation"),
                    "empfehlung": e.get("empfehlung"),
                    "weg": e.get("weg"),
                    "kontakt": kontakt(e.get("kontakt")),
                    "anfrage": anfrage(vorlage, e) if e.get("anfrage") else None,
                    "recht": recht.get(e.get("land")),
                    "links": [{"titel": t, "url": u} for t, u in e.get("links", [])],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def datenlage_md(fc: dict, erzeugt: str) -> str:
    """Übersicht für GitHub (docs/DATENLAGE.md) aus denselben Daten wie die Karte."""
    zeilen = [
        "# Datenlage: Geschwindigkeitskontrollen je Stadt",
        "",
        f"Erzeugt von `kontrollen site` am {erzeugt} aus `pipeline/config/sources.yaml` – nicht",
        "von Hand ändern. Dieselben Angaben zeigt die Karte unter „Datenlage je Stadt“. Rechtliche",
        "Hinweise sind keine Rechtsberatung; Kontakte über die Behördensuche von FragDenStaat.",
        "",
        "| Stadt | Land | Stand | Was es gibt |",
        "|---|---|---|---|",
    ]
    reihenfolge = list(STAND)
    eintraege = sorted(
        fc["features"],
        key=lambda f: (reihenfolge.index(f["properties"]["stand"]), f["properties"]["kommune"]),
    )
    for f in eintraege:
        p = f["properties"]
        zeilen.append(
            f"| {p['kommune']} | {p['land'] or ''} | {STAND[p['stand']]} | {p.get('was') or ''} |"
        )
    for f in eintraege:
        p = f["properties"]
        zeilen += ["", f"## {p['kommune']} ({p['land']}) – {STAND[p['stand']]}", ""]
        if p.get("kontrollen"):
            zeilen += [f"{p['kontrollen']:,} Kontrollen in der Karte.".replace(",", "."), ""]
        zeilen += [f"**Lage:** {p.get('situation') or p.get('was')}", ""]
        if p.get("empfehlung"):
            zeilen += [f"**Empfehlung:** {p['empfehlung']}", ""]
        if p.get("weg"):
            zeilen += [f"**Weg:** {p['weg']}", ""]
        if p.get("recht"):
            zeilen += [f"**Rechtslage im Land:** {p['recht']}", ""]
        k = p.get("kontakt") or {}
        if k.get("fds"):
            zeilen += [f"**Kontakt:** [Behörde auf FragDenStaat suchen]({k['fds']})", ""]
        if p.get("anfrage"):
            zeilen += [
                f"**Anfragetext** – Betreff: {p['anfrage']['betreff']}",
                "",
                "```text",
                p["anfrage"]["text"],
                "```",
                "",
            ]
        if p.get("links"):
            zeilen += [
                "**Belege:** " + " · ".join(f"[{x['titel']}]({x['url']})" for x in p["links"]),
                "",
            ]
    return "\n".join(zeilen).rstrip() + "\n"


def _stufen(t: pd.DataFrame) -> list[str] | None:
    """Beschriftung der beiden Stufen nach der häufigsten Grenze der Stadt (Berlin 20 km/h,
    Aachen meist 15 km/h); ohne Stufen in den Daten None."""
    k = t["stufe_kmh"].dropna()
    if k.empty:
        return None
    g = int(k.mode().iloc[0])
    return [f"bis {g} km/h", f"über {g} km/h"]


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
