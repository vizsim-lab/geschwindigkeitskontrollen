# SPDX-License-Identifier: AGPL-3.0-or-later
"""Datenlage: Anfragetext, Kontakt, Punkte aus den Messstellen, Prüfungen der Einträge."""

import pandas as pd
import pytest

from kontrollen import site
from kontrollen.config import quellen

VORLAGE = {"betreff": "B", "text": "{stelle} seit {seit}.\n{zusatz}\nEnde"}
Q = {
    "staedte": {"berlin": {}},
    "anfrage_vorlage": VORLAGE,
    "recht": {"BE": "Berliner IFG"},
}
STELLEN = [
    {"stadt": "berlin", "lon": 13.0, "lat": 52.0},
    {"stadt": "berlin", "lon": 13.2, "lat": 52.6},
    {"stadt": "berlin", "lon": 13.4, "lat": 52.4},
]
M = pd.DataFrame({"stadt": ["berlin"] * 5})


def test_anfrage_vorgaben_und_zusatz():
    a = site.anfrage(VORLAGE, {"kommune": "Essen"})
    assert a == {"betreff": "B", "text": "die Stadt Essen seit dem 1. Januar 2019.\n\nEnde"}
    b = site.anfrage(VORLAGE, {"kommune": "X", "stelle": "die Polizei X", "seit": "2020",
                               "anfrage_zusatz": "  mehr\n  Text "})  # fmt: skip
    assert b["text"] == "die Polizei X seit 2020.\n\nmehr Text\n\nEnde"


def test_kontakt_nur_ueber_fragdenstaat():
    k = site.kontakt({"fds_suche": "Polizei Hamburg"})
    assert k == {"fds": "https://fragdenstaat.de/behoerden/?q=Polizei+Hamburg", "fds_suche": True}
    assert site.kontakt(None) is None


def test_punkt_aus_den_messstellen():
    q = {
        **Q,
        "datenlage": [{"kommune": "Berlin", "stadt": "berlin", "land": "BE", "stand": "in_karte"}],
    }
    f = site.datenlage(q, STELLEN, M)["features"][0]
    assert f["geometry"]["coordinates"] == [13.2, 52.4]  # Median
    assert f["properties"]["kontrollen"] == 5
    assert f["properties"]["recht"] == "Berliner IFG"


def test_stadt_ohne_kontrollen_faellt_weg():
    q = {**Q, "datenlage": [{"kommune": "Berlin", "stadt": "berlin", "stand": "in_karte"}]}
    assert site.datenlage(q, [], M.iloc[:0])["features"] == []


@pytest.mark.parametrize(
    "eintrag, fehler",
    [
        ({"kommune": "X", "stand": "vielleicht", "lon": 1, "lat": 2}, "Stand"),
        ({"kommune": "X", "stand": "offen"}, "lon/lat"),
        ({"kommune": "X", "stand": "in_karte", "stadt": "paris"}, "staedte"),
    ],
)
def test_falsche_eintraege(eintrag, fehler):
    with pytest.raises(ValueError, match=fehler):
        site.datenlage({**Q, "datenlage": [eintrag]}, STELLEN, M)


def test_eintraege_in_sources_yaml():
    """Jeder Eintrag: bekannter Stand, Beleg, Ort; Anfragen nur mit Vorlage-tauglichen Feldern."""
    q = quellen()
    namen = [e["kommune"] for e in q["datenlage"]]
    assert len(namen) == len(set(namen)), "Kommune doppelt"
    for e in q["datenlage"]:
        assert e["stand"] in site.STAND, e["kommune"]
        assert e.get("links"), f"{e['kommune']}: ohne Beleg"
        assert e.get("stadt") in q["staedte"] or (e.get("lon") and e.get("lat")), e["kommune"]
        assert e.get("land") in q["recht"], (
            f"{e['kommune']}: Land {e.get('land')!r} ohne Rechtslage"
        )
        if e.get("anfrage"):
            site.anfrage(q["anfrage_vorlage"], e)  # Platzhalter passen
        if e.get("kontakt"):
            assert set(e["kontakt"]) <= {"fds_suche"}, f"{e['kommune']}: nur die Behördensuche"
