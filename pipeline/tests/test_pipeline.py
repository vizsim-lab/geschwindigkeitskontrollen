"""Die ganze Kette build -> geocode -> site an ausgedachten Daten (tests/fixtures/mini.osm)."""

import datetime as dt
import json

import openpyxl
import pandas as pd
import pytest
from anlage_pdf import anlage, zeile

from kontrollen import cli, osm
from kontrollen.config import get_paths

# je Jahr eine Anlage wie die Polizei-PDFs (tests/anlage_pdf.py)
ANLAGEN = {
    "anlage1_2017.pdf": [
        # Kreuzung, über Mitternacht
        zeile("1", "11", "Hauptstr.", "", "/Eckallee", "Mitte", "Osten/Stadtgrenze", "30",
              "07.07.2017", "22:00", "1:00", "500", "50", "45", "5", "0"),
    ],
    "anlage2_2018.pdf": [
        # Hausnummer im Abschnitt
        zeile("1", "11", "Hauptstr.", "10", "Querweg u. Nebenstr.", "Mitte", "Osten/Eckallee",
              "50", "01.03.2018", "8:00", "12:00", "1.000", "100", "90", "10", "1"),
        # Hausnummer an einer zweiten Straße
        zeile("1", "11", "Charlottenburger Chaussee", "43", "Am Rain u. Wiesendamm", "Mitte",
              "Westen/Am Rain", "50", "01.01.2018", "10:00", "12:00", "300", "30", "25", "5", "0"),
        # Autobahn: nur zu schnelle erfasst (Messungen = Überschreitungen)
        zeile("2", "21", "BAB A 100", "L4700", "AS Kaiserdamm", "Mitte", "Westen/AD Funkturm",
              "80", "02.02.2018", "10:00", "14:00", "200", "200", "150", "50", "10"),
        # gibt es nicht
        zeile("1", "11", "Gibtsnichtweg", "5", "A u. B", "Mitte", "Norden/X", "30",
              "02.02.2018", "10:00", "11:00", "10", "1", "1", "0", "0"),
    ],
    "anlage3_2019.pdf": [
        # dieselbe Stelle, andere Richtung
        zeile("1", "11", "Hauptstr.", "10", "Querweg u. Nebenstr.", "Mitte", "Westen/Querweg",
              "50", "02.05.2019", "9:00", "11:00", "800", "80", "70", "5", "0"),
    ],
    "anlage4_2020.pdf": [
        # wechselndes Tempolimit, Fahrverbote ohne Angabe
        zeile("1", "11", "Hauptstr.", "10", "Querweg u. Nebenstr.", "Mitte", "Osten/Eckallee",
              "30/50", "03.02.2020", "10:00", "12:00", "600", "30", "28", "2", "-"),
    ],
}  # fmt: skip


@pytest.fixture()
def daten(tmp_path, monkeypatch, auszug):
    monkeypatch.setenv("KONTROLLEN_DATA", str(tmp_path))
    p = get_paths()
    for name, zeilen in ANLAGEN.items():
        anlage(p.raw / "berlin" / name, zeilen)
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
    assert df["stadt"].value_counts().to_dict() == {"berlin": 7, "aachen": 1}
    bericht = json.loads((p.interim / "build_bericht.json").read_text())
    assert [a["zeilen"] for a in bericht["berlin_anlagen"]] == [1, 4, 1, 1]

    cli.geocode_cmd("alle")
    geo = pd.read_csv(p.data_file("geokodierung.csv"))
    methoden = dict(zip(geo["id"], geo["geo_methode"], strict=True))
    assert methoden["B2018-00001"] == "hausnummer"
    assert methoden["B2017-00001"] == "kreuzung"
    assert methoden["B2018-00002"] == "hausnummer"
    assert methoden["B2018-00003"] == "anschlussstelle"
    assert pd.isna(methoden["B2018-00004"])
    val = json.loads(p.data_file("geokodierung_validierung.json").read_text())
    assert val["berlin"]["ohne_lage"] == 1
    assert val["berlin"]["hausnummer_gegen_abschnitt"]["im_abschnitt"] == 1.0

    cli.site_cmd()
    stellen = json.loads((p.karte / "messstellen.json").read_text())
    kontrollen = json.loads((p.karte / "kontrollen.json").read_text())
    assert stellen["felder"][:4] == ["id", "stadt", "lon", "lat"]
    # Reihenfolge: Anlagen 1–4, dann Aachen
    z = kontrollen["zeilen"]
    f = {k: kontrollen["felder"].index(k) for k in ("stelle", "alle", "tempo", "fahrverbote")}
    assert len(z) == 8
    # die drei Kontrollen an Hauptstraße 10 sind eine Messstelle
    assert z[1][f["stelle"]] == z[5][f["stelle"]] == z[6][f["stelle"]] is not None
    assert z[4][f["stelle"]] is None  # ohne Lage
    assert z[3][f["alle"]] == 0  # Autobahn: nur zu schnelle erfasst
    assert z[6][f["tempo"]] is None and z[6][f["fahrverbote"]] is None  # "30/50", "-"
    manifest = json.loads((p.karte / "manifest.json").read_text())
    assert manifest["staedte"]["berlin"]["kontrollen"] == 7
    assert manifest["staedte"]["berlin"]["jahre"] == [2017, 2018, 2019, 2020]
    assert manifest["staedte"]["aachen"]["jahre"] == [2021]
    assert set(manifest["dateien"]) == {"messstellen", "kontrollen", "abschnitte", "csv"}
    abschn = json.loads((p.karte / "abschnitte.geojson").read_text())
    assert abschn["features"], "Abschnitt Querweg–Nebenstraße fehlt"
    csv = pd.read_csv(p.karte / "kontrollen.csv")
    assert {"lon", "lat", "verortung", "messstelle"} <= set(csv.columns)
