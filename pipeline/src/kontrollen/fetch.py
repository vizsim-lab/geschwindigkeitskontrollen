# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rohdaten holen: Berlin (feste CSV mit Prüfsumme), Aachen (alle Monatsdateien über CKAN),
OSM-Abzüge (Geofabrik).

Aachen: `fetch --aachen --neu` fragt die CKAN-Kataloge (sources.yaml) nach allen Datensätzen
„Geschwindigkeitskontrollen …“ der Stadt Aachen und schreibt die gefundenen Ressourcen samt
Prüfsumme nach config/aachen_ressourcen.json. Ohne --neu lädt `fetch` genau diese Liste – so
bleibt ein Lauf nachvollziehbar, und neue Monate kommen nur bewusst dazu.
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
    tmp.replace(ziel)
    return ziel


# --- Berlin --------------------------------------------------------------------------------


def berlin(paths: Paths | None = None) -> Path:
    paths = paths or get_paths()
    q = quellen(paths)["staedte"]["berlin"]["kontrollen"]
    return lade(q["url"], paths.data_file(q["datei"]), q["sha256"])


# --- Aachen --------------------------------------------------------------------------------


def _ckan(basis: str, aktion: str, **params) -> dict:
    r = requests.get(basis + aktion, params=params, timeout=60, headers=UA)
    r.raise_for_status()
    js = r.json()
    if not js.get("success"):
        raise RuntimeError(f"CKAN {aktion}: {js.get('error')}")
    return js["result"]


def aachen_katalog(cfg: dict) -> dict:
    """Alle passenden Datensätze und Ressourcen aus dem ersten CKAN, der antwortet."""
    titel = re.compile(cfg["titel_muster"])
    stadt = re.compile(cfg["aachen_muster"])
    formate = {f.upper() for f in cfg["formate"]}
    fehler = []
    for basis in cfg["ckan"]:
        try:
            datensaetze, start = [], 0
            while True:
                res = _ckan(basis, "package_search", q=cfg["suche"], rows=100, start=start)
                datensaetze += res["results"]
                start += 100
                if start >= res["count"]:
                    break
        except (requests.RequestException, RuntimeError, ValueError) as e:
            fehler.append(f"{basis}: {e}")
            continue
        treffer = []
        for d in datensaetze:
            org = (d.get("organization") or {}).get("title") or ""
            text = " ".join([d.get("title") or "", d.get("name") or "", org])
            if not titel.search(d.get("title") or "") or not stadt.search(text):
                continue
            res = []
            for r in d.get("resources", []):
                fmt = (r.get("format") or Path(urlparse(r.get("url", "")).path).suffix[1:]).upper()
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
            treffer.append(
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
        if treffer:
            return {"katalog": basis, "datensaetze": treffer, "fehler": fehler}
        fehler.append(f"{basis}: keine passenden Datensätze ({len(datensaetze)} gesucht)")
    raise RuntimeError("Kein CKAN-Katalog lieferte Aachener Daten:\n" + "\n".join(fehler))


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


def aachen(paths: Paths | None = None, *, neu: bool = False) -> list[Path]:
    """Monatsdateien laden; mit `neu` vorher den Katalog fragen und die Liste neu schreiben."""
    paths = paths or get_paths()
    cfg = quellen(paths)["staedte"]["aachen"]["kontrollen"]
    liste = paths.pipeline / cfg["ressourcen"]
    ordner = paths.data_file(cfg["ordner"])
    if neu or not liste.exists():
        katalog = aachen_katalog(cfg)
        dateien = []
        for d in katalog["datensaetze"]:
            for r in d["ressourcen"]:
                name = _dateiname(d["name"], r)
                ziel = lade(r["url"], ordner / name, neu=True)
                dateien.append({**r, "datensatz": d["name"], "datei": name, "sha256": sha256(ziel)})
        katalog["dateien"] = sorted(dateien, key=lambda x: x["datei"])
        for d in katalog["datensaetze"]:
            d.pop("ressourcen", None)
        liste.write_text(json.dumps(katalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    katalog = json.loads(liste.read_text(encoding="utf-8"))
    out = []
    for f in katalog["dateien"]:
        out.append(lade(f["url"], ordner / f["datei"], f["sha256"]))
    return out


# --- OSM -----------------------------------------------------------------------------------


def osm(stadt: str, paths: Paths | None = None, *, neu: bool = False) -> Path:
    paths = paths or get_paths()
    q = quellen(paths)["staedte"][stadt]["osm"]
    return lade(q["url"], paths.data_file(q["datei"]), neu=neu)
