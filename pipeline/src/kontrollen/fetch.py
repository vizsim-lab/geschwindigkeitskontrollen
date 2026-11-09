# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rohdaten holen: Berlin (die PDF-Anlagen, mit Prüfsumme), Aachen, Köln und Bonn (alle
passenden Dateien aus den Open-Data-Katalogen), OSM-Abzüge (Geofabrik).

Kataloge: `fetch --neu` fragt die CKAN-Kataloge (sources.yaml) nach den passenden Datensätzen
der Stadt und schreibt die gefundenen Ressourcen samt Prüfsumme nach config/<stadt>_ressourcen.json.
Ohne --neu lädt `fetch` genau diese Liste – so bleibt ein Lauf nachvollziehbar, und neue Monate
oder Jahre kommen nur bewusst dazu.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from kontrollen.config import Paths, get_paths, quellen

UA = {
    "User-Agent": "vizsim-geschwindigkeitskontrollen (+https://github.com/vizsim-lab/geschwindigkeitskontrollen)"
}


def sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with pfad.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def lade(url: str, ziel: Path, pruefsumme: str | None = None, *, neu: bool = False) -> Path:
    if ziel.exists() and not neu and (pruefsumme is None or sha256(ziel) == pruefsumme):
        return ziel
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_suffix(ziel.suffix + ".part")
    for versuch in range(3):
        try:
            with requests.get(url, stream=True, timeout=180, headers=UA) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for block in r.iter_content(1 << 20):
                        f.write(block)
            break
        except requests.RequestException:
            if versuch == 2:
                raise
            time.sleep(5 * (versuch + 1))
    if pruefsumme and sha256(tmp) != pruefsumme:
        tmp.unlink()
        raise ValueError(f"Prüfsumme stimmt nicht: {url}")
    if ziel.suffix.lower() == ".pdf" and tmp.read_bytes()[:5] != b"%PDF-":
        tmp.unlink()  # etwa eine Vorschauseite statt der Datei
        raise ValueError(f"Keine PDF-Datei: {url}")
    tmp.replace(ziel)
    return ziel


# --- Berlin --------------------------------------------------------------------------------


def berlin(paths: Paths | None = None) -> list[Path]:
    """Die PDF-Anlagen des IFG-Bescheids (2017 bis August 2020)."""
    paths = paths or get_paths()
    k = quellen(paths)["staedte"]["berlin"]["kontrollen"]
    return [lade(a["url"], paths.data_file(a["datei"]), a.get("sha256")) for a in k["anlagen"]]


# --- Open-Data-Kataloge (Aachen, Köln, Bonn) ----------------------------------------------


def _ckan(basis: str, aktion: str, **params) -> dict:
    r = requests.get(basis + aktion, params=params, timeout=60, headers=UA)
    r.raise_for_status()
    js = r.json()
    if not js.get("success"):
        raise RuntimeError(f"CKAN {aktion}: {js.get('error')}")
    return js["result"]


def _liste(v) -> list:
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _suche(basis: str, q: str) -> list[dict]:
    """Alle Treffer einer Suche (seitenweise; DKAN-Kataloge ignorieren `start` mitunter)."""
    datensaetze, start, gesehen = [], 0, set()
    while True:
        res = _ckan(basis, "package_search", q=q, rows=100, start=start)
        neu = [d for d in res.get("results", []) if d.get("id", d.get("name")) not in gesehen]
        gesehen |= {d.get("id", d.get("name")) for d in neu}
        datensaetze += neu
        start += 100
        if not neu or start >= int(res.get("count") or 0):
            return datensaetze


def _format(r: dict) -> str:
    """ "CSV", "csv", "text/csv" -> "CSV"; ohne Angabe die Dateiendung."""
    fmt = (r.get("format") or "").split("/")[-1].strip().upper()
    return fmt or Path(urlparse(r.get("url", "")).path).suffix[1:].upper()


def treffer(datensaetze: list[dict], cfg: dict, basis: str) -> list[dict]:
    """Datensätze, deren Titel zu `titel_muster` und deren Titel/Name/Organisation zur Stadt
    passen, mit ihren Ressourcen der gewünschten Formate."""
    titel = [re.compile(m) for m in _liste(cfg["titel_muster"])]
    stadt = re.compile(cfg.get("stadt_muster") or cfg["aachen_muster"])
    formate = {f.upper() for f in cfg["formate"]}
    out = []
    for d in datensaetze:
        org = (d.get("organization") or {}).get("title") or ""
        text = " ".join([d.get("title") or "", d.get("name") or "", org])
        if not any(t.search(d.get("title") or "") for t in titel) or not stadt.search(text):
            continue
        res = []
        for r in d.get("resources", []):
            fmt = _format(r)
            if fmt not in formate or not r.get("url"):
                continue
            res.append(
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "format": fmt,
                    "url": r["url"],
                    "geaendert": r.get("last_modified") or r.get("metadata_modified"),
                }
            )
        out.append(
            {
                "name": d.get("name"),
                "titel": d.get("title"),
                "organisation": org,
                "lizenz": d.get("license_title") or d.get("license_id"),
                "lizenz_id": d.get("license_id"),
                "lizenz_url": d.get("license_url"),
                "url": _datensatz_url(basis, d.get("name")),
                "ressourcen": res,
            }
        )
    return out


def _titel_schluessel(d: dict) -> str:
    return re.sub(r"[^0-9a-zäöüß]+", "", (d.get("titel") or d.get("name") or "").lower())


def katalog(cfg: dict) -> dict:
    """Passende Datensätze aus den CKAN-Katalogen in `cfg["ckan"]`.

    Standard (Aachen): der erste Katalog, der etwas findet. Mit `alle_kataloge` werden alle
    gefragt und die Funde vereinigt – derselbe Titel ist derselbe Datensatz, es zählt der Fund
    mit den meisten Ressourcen (Landesportale spiegeln die Städte oft unvollständig)."""
    fehler: list[str] = []
    funde: dict[str, tuple[str, dict]] = {}
    for basis in cfg["ckan"]:
        try:
            gefunden: dict[str, dict] = {}
            for q in _liste(cfg["suche"]):
                for d in _suche(basis, q):
                    gefunden.setdefault(d.get("id") or d.get("name"), d)
        except (requests.RequestException, RuntimeError, ValueError) as e:
            fehler.append(f"{basis}: {e}")
            continue
        t = treffer(list(gefunden.values()), cfg, basis)
        if not t:
            fehler.append(f"{basis}: keine passenden Datensätze ({len(gefunden)} gesucht)")
            continue
        for d in t:
            k = _titel_schluessel(d)
            if k not in funde or len(d["ressourcen"]) > len(funde[k][1]["ressourcen"]):
                funde[k] = (basis, d)
        if not cfg.get("alle_kataloge"):
            break
    if not funde:
        raise RuntimeError("Kein CKAN-Katalog lieferte passende Daten:\n" + "\n".join(fehler))
    kataloge = sorted({b for b, _ in funde.values()}, key=cfg["ckan"].index)
    datensaetze = [d for _, d in funde.values()]  # Reihenfolge der Suche (stabil für Aachen)
    return {"katalog": " ".join(kataloge), "datensaetze": datensaetze, "fehler": fehler}


def aachen_katalog(cfg: dict) -> dict:
    """Alle passenden Datensätze und Ressourcen aus dem ersten CKAN, der antwortet."""
    return katalog(cfg)


def _datensatz_url(basis: str, name: str | None) -> str | None:
    if not name:
        return None
    u = urlparse(basis)
    return f"{u.scheme}://{u.netloc}/dataset/{name}"


def _dateiname(ds: str, r: dict) -> str:
    """Sprechender, stabiler Dateiname: <Datensatz>__<Ressourcenname oder URL-Name>.<endung>"""
    endung = Path(unquote(urlparse(r["url"]).path)).suffix.lower() or "." + r["format"].lower()
    basis = r.get("name") or Path(unquote(urlparse(r["url"]).path)).stem
    sauber = re.sub(r"[^0-9A-Za-zÄÖÜäöüß_-]+", "_", f"{ds}__{basis}").strip("_")
    return sauber[:150] + endung


def ckan_dateien(stadt: str, paths: Paths | None = None, *, neu: bool = False) -> list[Path]:
    """Dateien einer Stadt aus ihren Open-Data-Katalogen laden; mit `neu` vorher die Kataloge
    fragen und die Liste (`ressourcen` in sources.yaml) neu schreiben. Ohne `neu` lädt `fetch`
    genau diese Liste – so bleibt ein Lauf nachvollziehbar, und Neues kommt nur bewusst dazu."""
    paths = paths or get_paths()
    cfg = quellen(paths)["staedte"][stadt]["kontrollen"]
    liste = paths.pipeline / cfg["ressourcen"]
    ordner = paths.data_file(cfg["ordner"])
    if neu or not liste.exists():
        kat = katalog(cfg)
        dateien, namen = [], set()
        for d in kat["datensaetze"]:
            for r in d["ressourcen"]:
                name = _dateiname(d["name"], r)
                if name in namen:  # dieselbe Ressource in zwei Katalogen
                    continue
                namen.add(name)
                try:
                    ziel = lade(r["url"], ordner / name, neu=True)
                except (requests.RequestException, ValueError) as e:
                    if not cfg.get("alle_kataloge"):
                        raise
                    kat["fehler"].append(f"{r['url']}: {e}")  # Spiegel ohne Datei: weiter
                    continue
                dateien.append({**r, "datensatz": d["name"], "datei": name, "sha256": sha256(ziel)})
        kat["dateien"] = sorted(dateien, key=lambda x: x["datei"])
        for d in kat["datensaetze"]:
            d.pop("ressourcen", None)
        liste.write_text(json.dumps(kat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    kat = json.loads(liste.read_text(encoding="utf-8"))
    out = [lade(f["url"], ordner / f["datei"], f["sha256"]) for f in kat["dateien"]]
    if cfg.get("alt"):  # Aachen: Juni 2020 aus der alten Karte
        a = cfg["alt"]
        out.append(lade(a["url"], paths.data_file(a["datei"]), a["sha256"]))
    return out


def aachen(paths: Paths | None = None, *, neu: bool = False) -> list[Path]:
    """Aachener Monatsdateien (siehe `ckan_dateien`)."""
    return ckan_dateien("aachen", paths, neu=neu)


# --- OSM -----------------------------------------------------------------------------------


def osm(stadt: str, paths: Paths | None = None, *, neu: bool = False) -> Path:
    paths = paths or get_paths()
    q = quellen(paths)["staedte"][stadt]["osm"]
    return lade(q["url"], paths.data_file(q["datei"]), neu=neu)
