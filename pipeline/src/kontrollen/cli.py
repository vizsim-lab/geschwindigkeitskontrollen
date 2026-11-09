# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kommandozeile: `uv run kontrollen <befehl>` (aus pipeline/)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import typer

from kontrollen import (
    aachen,
    berlin,
    bonn,
    fetch,
    geocode,
    koeln,
    oberderdingen,
    osm,
    schonungen,
    site,
)  # fmt: skip
from kontrollen.config import get_paths, load_yaml, quellen

app = typer.Typer(no_args_is_help=True, help="Pipeline der Karte der Geschwindigkeitskontrollen")


def staedte() -> tuple[str, ...]:
    """Alle Städte aus sources.yaml, in deren Reihenfolge."""
    return tuple(quellen()["staedte"])


def _staedte(stadt: str) -> tuple[str, ...]:
    alle = staedte()
    if stadt == "alle":
        return alle
    if stadt not in alle:
        raise typer.BadParameter(f"Stadt {stadt!r} unbekannt – {', '.join(alle)} oder alle")
    return (stadt,)


@app.command()
def info() -> None:
    """Pfade, Quellen und was davon schon da ist."""
    p = get_paths()
    q = quellen(p)
    typer.echo(f"Daten: {p.data}")
    for code, s in q["staedte"].items():
        k, o = s["kontrollen"], s["osm"]
        for d in [a["datei"] for a in k.get("anlagen", [])] or [k.get("datei") or k["ordner"]]:
            ziel = p.data_file(d)
            typer.echo(f"{code}: Kontrollen {'da' if ziel.exists() else 'fehlt'} ({ziel})")
        typer.echo(f"{code}: OSM {'da' if p.data_file(o['datei']).exists() else 'fehlt'}")
    for name in ("interim/kontrollen.parquet", "geokodierung.csv", "karte/manifest.json"):
        typer.echo(f"{name}: {'da' if p.data_file(name).exists() else 'fehlt'}")


@app.command("fetch")
def fetch_cmd(
    berlin_: bool = typer.Option(True, "--berlin/--ohne-berlin"),
    aachen_: bool = typer.Option(True, "--aachen/--ohne-aachen"),
    andere: bool = typer.Option(True, "--andere/--ohne-andere", help="Köln, Bonn, …"),
    mit_osm: bool = typer.Option(False, "--osm", help="auch die OSM-Abzüge (Geofabrik)"),
    neu: bool = typer.Option(False, "--neu", help="Kataloge neu fragen; OSM: neu laden"),
) -> None:
    """Rohdaten laden (Berliner PDF-Anlagen, Dateien der Open-Data-Kataloge, optional OSM).

    Scheitert eine Stadt aus den Katalogen (Köln, Bonn, …), laufen die übrigen weiter; der
    Befehl endet dann mit Fehlercode 1."""
    fehler = []
    if berlin_:
        typer.echo(f"Berlin: {fetch.berlin()}")
    if aachen_:
        dateien = fetch.aachen(neu=neu)
        typer.echo(f"Aachen: {len(dateien)} Dateien")
    q = quellen()["staedte"]
    for s in staedte():
        k = q[s]["kontrollen"]
        if s in ("berlin", "aachen") or not andere or not ("ckan" in k or "kataloge" in k):
            continue
        try:
            dateien = fetch.ckan_dateien(s, neu=neu)
            typer.echo(f"{q[s]['label']}: {len(dateien)} Dateien")
        except Exception as e:  # noqa: BLE001 – eine Stadt darf die anderen nicht aufhalten
            fehler.append(s)
            typer.echo(f"{q[s]['label']}: FEHLER {e}", err=True)
    if mit_osm:
        geladen: dict[str, Path] = {}
        for s in staedte():
            datei = q[s]["osm"]["datei"]
            if datei not in geladen:  # Aachen, Köln und Bonn teilen sich einen Abzug
                geladen[datei] = fetch.osm(s, neu=neu)
            typer.echo(f"OSM {s}: {geladen[datei]}")
    if fehler:
        raise typer.Exit(1)


@app.command("osm")
def osm_cmd(stadt: str = typer.Option("alle", help="Stadt (berlin, aachen, …) oder alle")) -> None:
    """OSM-PBF -> data/interim/osm/{strassen,adressen,knoten,gebiete}_<stadt>.parquet"""
    p = get_paths()
    for s in _staedte(stadt):
        cfg = quellen(p)["staedte"][s]
        a = osm.lies(
            p.data_file(cfg["osm"]["datei"]), cfg["bbox"], cfg["osm"]["gebiete_admin_level"]
        )
        osm.schreibe(a, p.interim / "osm", s)
        typer.echo(
            f"{s}: {len(a.strassen)} Straßenstücke, {len(a.adressen)} Adressen, "
            f"{len(a.knoten)} Anschlussstellen, {len(a.gebiete)} Gebiete"
        )


def _katalogdateien(p, cfg: dict) -> list[Path]:
    """Die Dateien einer Stadt aus den Katalogen (Liste `ressourcen`); fehlt sie, der Ordner."""
    k = cfg["kontrollen"]
    ordner = p.data_file(k["ordner"])
    liste = p.pipeline / k["ressourcen"]
    if liste.exists():
        namen = [f["datei"] for f in json.loads(liste.read_text(encoding="utf-8"))["dateien"]]
        dateien = [ordner / n for n in namen]
        # im Entwicklungsauszug liegen große CSV gzip-komprimiert
        return [d if d.exists() else d.with_name(d.name + ".gz") for d in dateien]
    return sorted(ordner.glob("*.csv")) + sorted(ordner.glob("*.csv.gz"))


# Städte aus Katalogen: Leser je Stadt (Dateien aus `_katalogdateien`) -> (Kontrollen, Bericht)
LESER = {
    "koeln": koeln.lies_alle,
    "bonn": bonn.lies_alle,
    "schonungen": schonungen.lies_alle,
    "oberderdingen": oberderdingen.lies_alle,
}


@app.command()
def build() -> None:
    """Rohdaten aller Städte -> data/interim/kontrollen.parquet (gemeinsames Schema)."""
    p = get_paths()
    q = quellen(p)["staedte"]
    anlagen = [(a, p.data_file(a["datei"])) for a in q["berlin"]["kontrollen"]["anlagen"]]
    b, berlin_bericht = berlin.lies(anlagen)
    ordner = p.data_file(q["aachen"]["kontrollen"]["ordner"])
    dateien = [f for f in sorted(ordner.glob("*")) if f.suffix.lower() in (".xlsx", ".xls", ".csv")]
    alt = q["aachen"]["kontrollen"].get("alt")
    a, hinweise = aachen.lies_alle(dateien, p.data_file(alt["datei"]) if alt else None)
    teile = [b, a]
    weitere: dict[str, dict] = {}
    for code, leser in LESER.items():
        if code not in q:
            continue
        fd = [f for f in _katalogdateien(p, q[code]) if f.exists()]
        if not fd:
            typer.echo(f"{q[code]['label']}: keine Rohdateien – übersprungen (fetch)", err=True)
            continue
        t, ber = leser(fd)
        teile.append(t)
        weitere[code] = {"kontrollen": int(len(t)), **ber}
    df = pd.concat(teile, ignore_index=True)
    p.interim.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p.interim / "kontrollen.parquet", index=False)
    bericht = {
        "berlin": int(len(b)),
        "berlin_anlagen": berlin_bericht,
        "aachen": int(len(a)),
        "aachen_dateien": len(dateien),
        "aachen_zeitraum": [a["datum"].min(), a["datum"].max()] if len(a) else None,
        "hinweise": hinweise,
        **weitere,
    }
    (p.interim / "build_bericht.json").write_text(
        json.dumps(bericht, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    typer.echo(
        json.dumps(
            {
                k: (v["kontrollen"] if k in weitere else v)
                for k, v in bericht.items()
                if k not in ("hinweise", "berlin_anlagen")
            },
            ensure_ascii=False,
        )
    )
    for a in berlin_bericht:
        typer.echo(
            f"  Berlin {a['jahr']}: {a['zeilen']} Zeilen auf {a['seiten']} Seiten, "
            f"{a['uebersprungen']} übersprungen, {a['fehler']} Fehler, "
            f"{a['andere_jahre']} aus anderen Jahren"
        )
    for h in hinweise[:40]:
        typer.echo(f"  Hinweis: {h}")


def netz_und_gebiete(s: str, paths=None) -> tuple[geocode.Netz, geocode.Gebiete]:
    p = paths or get_paths()
    cfg = quellen(p)["staedte"][s]
    a = osm.lade(p.interim / "osm", s)
    ortsnamen = (load_yaml("orte.yaml", p) or {}).get(s) or {}
    netz = geocode.Netz.aus_auszug(a, cfg["crs_m"], ortsnamen)
    gebiete = geocode.Gebiete.aus_auszug(
        a, cfg["crs_m"], {**cfg["osm"], "bbox": cfg["bbox"]}, cfg["osm"].get("bezirk_ebene")
    )
    return netz, gebiete


@app.command("geocode")
def geocode_cmd(
    stadt: str = typer.Option("alle", help="Stadt (berlin, aachen, …) oder alle"),
) -> None:
    """Kontrollen verorten -> data/geokodierung.csv + geokodierung_validierung.json"""
    p = get_paths()
    df = pd.read_parquet(p.interim / "kontrollen.parquet")
    ziel = p.data_file("geokodierung.csv")
    alt = pd.read_csv(ziel, dtype=str) if ziel.exists() else None
    teile = []
    for s in _staedte(stadt):
        t = df[df["stadt"] == s]
        if t.empty:
            continue
        netz, gebiete = netz_und_gebiete(s, p)
        geo = geocode.verorte_tabelle(t, netz, gebiete)
        teile.append(geo)
        typer.echo(f"{s}: {geo['geo_methode'].value_counts(dropna=False).to_dict()}")
    geo = pd.concat(teile, ignore_index=True)
    if alt is not None and stadt != "alle":  # andere Stadt behalten
        andere = df.loc[~df["stadt"].isin(_staedte(stadt)), "id"]
        geo = pd.concat([alt[alt["id"].isin(andere)], geo], ignore_index=True)
    geo = geo.set_index("id").reindex(df["id"]).reset_index()
    geo.to_csv(ziel, index=False)
    val = geocode.validiere(df, geo)
    Path(p.data_file("geokodierung_validierung.json")).write_text(
        json.dumps(val, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    typer.echo(json.dumps(val, ensure_ascii=False, indent=1))


@app.command("site")
def site_cmd() -> None:
    """Kartendaten -> data/karte/* (Messstellen, Kontrollen, Abschnitte, CSV, Manifest)."""
    bericht = site.baue(get_paths())
    typer.echo(json.dumps(bericht, ensure_ascii=False, indent=1))


@app.command()
def alles(mit_osm: bool = typer.Option(False, "--osm", help="OSM neu laden und auslesen")) -> None:
    """fetch + build + (osm, geocode) + site"""
    fetch_cmd(berlin_=True, aachen_=True, andere=True, mit_osm=mit_osm, neu=False)
    if mit_osm:
        osm_cmd("alle")
    build()
    if (get_paths().interim / "osm" / "strassen_berlin.parquet").exists():
        geocode_cmd("alle")
    site_cmd()


if __name__ == "__main__":
    app()
