"""Die ganze Kette build -> geocode -> site an ausgedachten Daten (tests/fixtures/mini.osm)."""

import datetime as dt
import json

import openpyxl
import pandas as pd
import pytest

from kontrollen import cli, osm
from kontrollen.config import get_paths

KOPF = (
    "Direktionsbereich;Abschnittsbereich;Straßenname;Nr.;zwischen;Verwaltungsbezirk;Richtung;"
    "erlaubte Geschwindigkeit;Messungen;Überschreitungen;bis 20 km/h;über 20 km/h;Fahrverbote;"
    "Beginn_date;Ende_date;duration"
)
ZEILEN = [
    # Hausnummer im Abschnitt, zweimal (eine Messstelle, zwei Richtungen)
    "1;11;Hauptstr.;10;Querweg u. Nebenstr.;Mitte;Osten/Eckallee;50;1000;100;90;10;1;2018-03-01 08:00:00;2018-03-01 12:00:00;0 days 04:00:00",
    "1;11;Hauptstr.;10;Querweg u. Nebenstr.;Mitte;Westen/Querweg;50;800;80;70;5;0;2019-05-02 09:00:00;2019-05-02 11:00:00;0 days 02:00:00",
    # Kreuzung
    "1;11;Hauptstr.;;/Eckallee;Mitte;Osten/Stadtgrenze;30;500;50;45;5;0;2017-07-07 22:00:00;2017-07-08 01:00:00;0 days 03:00:00",
    # abgeschnittener Name mit Überlauf ins Feld Nr.
    "1;11;Charlottenburger Chauss;ee 43;Am Rain u. Wiesendamm;Mitte;Westen/Am Rain;50;300;30;25;5;0;2018-01-01 10:00:00;2018-01-01 12:00:00;0 days 02:00:00",
    # Autobahn: nur zu schnelle erfasst (Messungen = Überschreitungen)
    "2;21;BAB A 100;L4700;AS Kaiserdamm;Mitte;Westen/AD Funkturm;80;200;200;150;50;10;2018-02-02 10:00:00;2018-02-02 14:00:00;0 days 04:00:00",
    # gibt es nicht
    "1;11;Gibtsnichtweg;5;A u. B;Mitte;Norden/X;30;10;1;1;0;0;2018-02-02 10:00:00;2018-02-02 11:00:00;0 days 01:00:00",
]


@pytest.fixture()
def daten(tmp_path, monkeypatch, auszug):
    monkeypatch.setenv("KONTROLLEN_DATA", str(tmp_path))
    p = get_paths()
    (p.raw / "berlin").mkdir(parents=True)
    (p.raw / "berlin" / "kontrollen_2017-2019_v01.csv").write_text(
        "\n".join([KOPF, *ZEILEN]) + "\n", encoding="utf-8"
    )
    (p.raw / "aachen").mkdir(parents=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(
        ["Datum", "Messplatz", "Fahrtrichtung", "Fahrzeuge gesamt", "bis 15 km/h", "über 15 km/h"]
    )
    ws.append([dt.datetime(2021, 4, 1), "Eckallee", "Hauptstraße", 400, 20, 1])
    wb.save(p.raw / "aachen" / "test.xlsx")
    for stadt in ("berlin", "aachen"):
        osm.schreibe(auszug, p.interim / "osm", stadt)
    return p


def test_kette(daten):
    p = daten
    cli.build()
    df = pd.read_parquet(p.interim / "kontrollen.parquet")
    assert df["stadt"].value_counts().to_dict() == {"berlin": 6, "aachen": 1}

    cli.geocode_cmd("alle")
    geo = pd.read_csv(p.data_file("geokodierung.csv"))
    methoden = dict(zip(geo["id"], geo["geo_methode"], strict=True))
    assert methoden["B00001"] == "hausnummer"
    assert methoden["B00003"] == "kreuzung"
    assert methoden["B00004"] == "hausnummer"
    assert methoden["B00005"] == "anschlussstelle"
    assert pd.isna(methoden["B00006"])
    val = json.loads(p.data_file("geokodierung_validierung.json").read_text())
    assert val["berlin"]["ohne_lage"] == 1
    assert val["berlin"]["hausnummer_gegen_abschnitt"]["im_abschnitt"] == 1.0

    cli.site_cmd()
    stellen = json.loads((p.karte / "messstellen.json").read_text())
    kontrollen = json.loads((p.karte / "kontrollen.json").read_text())
    assert stellen["felder"][:4] == ["id", "stadt", "lon", "lat"]
    assert len(kontrollen["zeilen"]) == 7
    # die beiden Kontrollen an Hauptstraße 10 sind eine Messstelle
    i = kontrollen["felder"].index("stelle")
    assert kontrollen["zeilen"][0][i] == kontrollen["zeilen"][1][i] is not None
    assert kontrollen["zeilen"][5][i] is None  # ohne Lage
    alle = kontrollen["felder"].index("alle")
    assert kontrollen["zeilen"][4][alle] == 0  # Autobahn: nur zu schnelle erfasst
    manifest = json.loads((p.karte / "manifest.json").read_text())
    assert manifest["staedte"]["berlin"]["kontrollen"] == 6
    assert manifest["staedte"]["aachen"]["jahre"] == [2021]
    assert set(manifest["dateien"]) == {"messstellen", "kontrollen", "abschnitte", "csv"}
    abschn = json.loads((p.karte / "abschnitte.geojson").read_text())
    assert abschn["features"], "Abschnitt Querweg–Nebenstraße fehlt"
    csv = pd.read_csv(p.karte / "kontrollen.csv")
    assert {"lon", "lat", "verortung", "messstelle"} <= set(csv.columns)
