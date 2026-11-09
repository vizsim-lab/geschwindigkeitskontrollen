# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kataloge: Treffer filtern, mehrere Kataloge vereinigen (ohne Netz, `_ckan` ersetzt)."""

import pytest

from kontrollen import fetch

KOELN = {
    "ckan": ["https://stadt.example/api/3/action/", "https://land.example/api/3/action/"],
    "alle_kataloge": True,
    "suche": ["Geschwindigkeitsüberwachung Köln"],
    "titel_muster": "(?i)geschwindigkeits(ü|ue)berwachung",
    "stadt_muster": "(?i)k(ö|oe)ln",
    "formate": ["CSV"],
}


def _ds(name, titel, *res, org="Stadt Köln"):
    return {
        "id": name,
        "name": name,
        "title": titel,
        "organization": {"title": org},
        "license_id": "dl-zero-de/2.0",
        "license_title": "Datenlizenz Deutschland – Zero – Version 2.0",
        "resources": [
            {"id": f"{name}-{i}", "name": n, "format": f, "url": u}
            for i, (n, f, u) in enumerate(res)
        ],
    }


def _katalog(monkeypatch, antworten):
    def ckan(basis, aktion, **params):
        if isinstance(antworten.get(basis), Exception):
            raise antworten[basis]
        if params.get("start", 0) > 0:
            return {"count": len(antworten[basis]), "results": []}
        return {"count": len(antworten[basis]), "results": antworten[basis]}

    monkeypatch.setattr(fetch, "_ckan", ckan)


def test_treffer_filtert_titel_stadt_und_format():
    ds = [
        _ds("gsu-koeln-2024", "Geschwindigkeitsüberwachung Köln 2024",
            ("Vorgänge 2024", "csv", "https://x/2024.csv"), ("Info", "PDF", "https://x/i.pdf")),
        _ds("gsu-bonn", "Messstellen der mobilen Geschwindigkeitsüberwachung", org="Bundesstadt Bonn"),
        _ds("radwege-koeln", "Radwege Köln", ("Radwege", "CSV", "https://x/r.csv")),
    ]  # fmt: skip
    t = fetch.treffer(ds, KOELN, "https://stadt.example/api/3/action/")
    assert [d["name"] for d in t] == ["gsu-koeln-2024"]
    assert [r["format"] for r in t[0]["ressourcen"]] == ["CSV"]
    assert t[0]["url"] == "https://stadt.example/dataset/gsu-koeln-2024"


def test_format_als_mimetype_oder_endung():
    assert fetch._format({"format": "text/csv"}) == "CSV"
    assert fetch._format({"format": "", "url": "https://x/a/b.CSV"}) == "CSV"


def test_alle_kataloge_vereinigt_und_nimmt_den_vollstaendigeren(monkeypatch):
    stadt = [
        _ds("gsu-2017-2022", "Geschwindigkeitsüberwachung Köln 2017 bis 2022",
            *[(f"Teil {i}", "CSV", f"https://stadt/{i}.csv") for i in range(7)]),
    ]  # fmt: skip
    land = [
        _ds("gsu-2017-2022-k", "Geschwindigkeitsüberwachung Köln 2017 bis 2022"),  # ohne Dateien
        _ds("gsu-ab-2023-k", "Geschwindigkeitsüberwachung Köln ab 2023",
            ("Vorgänge 2023", "CSV", "https://land/2023.csv")),
    ]  # fmt: skip
    _katalog(monkeypatch, {KOELN["ckan"][0]: stadt, KOELN["ckan"][1]: land})
    k = fetch.katalog(KOELN)
    namen = {d["name"]: len(d["ressourcen"]) for d in k["datensaetze"]}
    assert namen == {"gsu-2017-2022": 7, "gsu-ab-2023-k": 1}
    assert k["katalog"] == " ".join(KOELN["ckan"])


def test_ohne_alle_kataloge_gewinnt_der_erste(monkeypatch):
    cfg = {**KOELN, "alle_kataloge": False}
    _katalog(monkeypatch, {
        cfg["ckan"][0]: [_ds("a", "Geschwindigkeitsüberwachung Köln A", ("A", "CSV", "https://s/a.csv"))],
        cfg["ckan"][1]: [_ds("b", "Geschwindigkeitsüberwachung Köln B", ("B", "CSV", "https://l/b.csv"))],
    })  # fmt: skip
    assert [d["name"] for d in fetch.katalog(cfg)["datensaetze"]] == ["a"]


def test_katalog_faellt_aus_und_der_naechste_hilft(monkeypatch):
    _katalog(monkeypatch, {
        KOELN["ckan"][0]: fetch.requests.ConnectionError("weg"),
        KOELN["ckan"][1]: [_ds("b", "Geschwindigkeitsüberwachung Köln B", ("B", "CSV", "https://l/b.csv"))],
    })  # fmt: skip
    k = fetch.katalog(KOELN)
    assert [d["name"] for d in k["datensaetze"]] == ["b"]
    assert k["fehler"] and "weg" in k["fehler"][0]


def test_nichts_gefunden(monkeypatch):
    _katalog(monkeypatch, {KOELN["ckan"][0]: [], KOELN["ckan"][1]: []})
    with pytest.raises(RuntimeError, match="Kein CKAN-Katalog"):
        fetch.katalog(KOELN)


def test_aachen_muster_gilt_weiter():
    cfg = {k: v for k, v in KOELN.items() if k != "stadt_muster"} | {"aachen_muster": "(?i)köln"}
    ds = [_ds("x", "Geschwindigkeitsüberwachung Köln", ("X", "CSV", "https://x/x.csv"))]
    assert len(fetch.treffer(ds, cfg, "https://s/api/3/action/")) == 1


class _Antwort:
    def __init__(self, js):
        self._js = js

    def raise_for_status(self):
        pass

    def json(self):
        return self._js


def test_dkan_suche_wie_ckan(monkeypatch):
    """Antwort von offenedaten-koeln.de (api/1/search, gekürzt) -> CKAN-Form -> Treffer."""
    import json
    from pathlib import Path

    js = json.loads(
        (Path(__file__).parent / "fixtures" / "dkan_suche_koeln.json").read_text("utf-8")
    )
    seiten = []
    monkeypatch.setattr(
        fetch.requests, "get", lambda url, params, **kw: seiten.append(params) or _Antwort(js)
    )
    ds = fetch._dkan_suche(
        "https://www.offenedaten-koeln.de/api/1/", "Geschwindigkeitsüberwachung Köln"
    )
    assert len(seiten) == 1  # alle Treffer auf der ersten Seite
    t = fetch.treffer(ds, KOELN, "https://www.offenedaten-koeln.de/api/1/")
    namen = {d["titel"]: len(d["ressourcen"]) for d in t}
    assert namen == {
        "Geschwindigkeitsüberwachung Köln 2017 bis 2022": 7,
        "Geschwindigkeitsüberwachung Köln 2025": 5,
    }
    d = next(x for x in t if x["titel"].endswith("2025"))
    assert d["lizenz_id"] == "dl-zero-de/2.0"
    assert d["lizenz"] == "Datenlizenz Deutschland – Zero – Version 2.0"
    assert d["organisation"] == "Stadt Köln"
    assert d["name"] == "geschwindigkeitsueberwachung-koeln-2025"
    assert all(r["format"] == "CSV" for r in d["ressourcen"])


def test_url_doppelt_kodiert():
    u = "https://x/Geschwindigkeit%25C3%25BCberwachung_Koeln.csv"
    assert fetch.url_varianten(u) == [u, "https://x/Geschwindigkeit%C3%BCberwachung_Koeln.csv"]
    assert fetch.url_varianten("https://x/a.csv") == ["https://x/a.csv"]


class _Datei:
    def __init__(self, code, inhalt=b"a;b\n1;2\n"):
        self.status_code, self._inhalt = code, inhalt

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise fetch.requests.HTTPError(f"{self.status_code}", response=self)

    def iter_content(self, n):
        yield self._inhalt


def _netz(monkeypatch, folge):
    """`requests.get` liefert der Reihe nach: Ausnahme (wird geworfen) oder Statuscode."""
    aufrufe, pausen = [], []

    def get(url, **kw):
        aufrufe.append(url)
        x = folge[len(aufrufe) - 1]
        if isinstance(x, Exception):
            raise x
        return _Datei(x)

    monkeypatch.setattr(fetch.requests, "get", get)
    monkeypatch.setattr(fetch.time, "sleep", pausen.append)
    return aufrufe, pausen


def test_lade_wartet_bei_abgewiesener_verbindung(tmp_path, monkeypatch):
    weg = fetch.requests.ConnectionError("Connection refused")
    aufrufe, pausen = _netz(monkeypatch, [weg, weg, 200])
    ziel = fetch.lade("https://opendata.example/a.csv", tmp_path / "a.csv")
    assert ziel.read_bytes() == b"a;b\n1;2\n"
    assert len(aufrufe) == 3 and pausen == list(fetch.WARTEN[:2])


def test_lade_gibt_bei_404_gleich_auf(tmp_path, monkeypatch):
    aufrufe, pausen = _netz(monkeypatch, [404, 200])
    with pytest.raises(fetch.requests.HTTPError):
        fetch.lade("https://opendata.example/fehlt.csv", tmp_path / "fehlt.csv")
    assert len(aufrufe) == 1 and pausen == []


def test_lade_gibt_nach_allen_versuchen_auf(tmp_path, monkeypatch):
    weg = fetch.requests.ConnectionError("Connection refused")
    aufrufe, pausen = _netz(monkeypatch, [weg] * (len(fetch.WARTEN) + 1))
    with pytest.raises(fetch.requests.ConnectionError):
        fetch.lade("https://opendata.example/a.csv", tmp_path / "a.csv")
    assert len(aufrufe) == len(fetch.WARTEN) + 1 and pausen == list(fetch.WARTEN)
