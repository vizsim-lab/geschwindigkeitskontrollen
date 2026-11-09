"""Aachener Monatsdateien: Kopfzeile finden, Spalten zuordnen, Zeilen lesen."""

import datetime as dt

import openpyxl

from kontrollen import aachen


def _xlsx(pfad, zeilen):
    wb = openpyxl.Workbook()
    ws = wb.active
    for z in zeilen:
        ws.append(z)
    wb.save(pfad)
    return pfad


def test_format_2020(tmp_path):
    # wie die Datei vom Juni 2020 (Spaltennamen wörtlich, mit Leerzeichen hinter "km/h")
    p = _xlsx(
        tmp_path / "juni2020.xlsx",
        [
            [
                "Datum",
                "Messplatz",
                "Fahrtrichtung",
                "Fahrzeuge gesamt",
                "bis 15 km/h  ",
                "über 15 km/h",
            ],
            [dt.datetime(2020, 6, 2), "Horbacher Straße", "Roermonder Straße", 408, 42, 1],
            [None, "Neuenhofstraße", "Debystraße", 348, 48, 3],
            [dt.datetime(2020, 6, 3), "Trierer Straße 312", "Stadtmitte", 120, 10, 0],
            ["Summe", "", "", 876, 100, 4],
        ],
    )
    df, hinweise = aachen.lies_datei(p)
    assert hinweise == []
    assert len(df) == 3
    r = df.iloc[0]
    assert (r.datum, r.strasse, r.richtung_ziel) == (
        "2020-06-02",
        "Horbacher Straße",
        "Roermonder Straße",
    )
    assert (r.messungen, r.stufe1, r.stufe2, r.ueberschreitungen) == (408, 42, 1, 43)
    assert bool(r.alle_gezaehlt)
    assert df.iloc[1].datum == "2020-06-02"  # Datum aus der Zeile darüber
    assert (df.iloc[2].strasse, df.iloc[2].hausnummer) == ("Trierer Straße", "312")
    assert df["tempo"].isna().all() and df["dauer_min"].isna().all()


def test_csv_mit_titelzeile_und_unbekannter_spalte(tmp_path):
    p = tmp_path / "okt.csv"
    p.write_text(
        "Geschwindigkeitskontrollen Oktober 2024;;;;;;\n"
        "Datum;Messplatz;Fahrtrichtung;zul. Geschwindigkeit;Fahrzeuge gesamt;Verwarngeld;Bußgeld;Bemerkung\n"
        "01.10.2024;Lütticher Straße;Ronheide;30;1.234;56;7;x\n",
        encoding="cp1252",
    )
    df, hinweise = aachen.lies_datei(p)
    assert len(df) == 1
    r = df.iloc[0]
    assert (r.datum, r.tempo, r.messungen, r.stufe1, r.stufe2) == ("2024-10-01", 30, 1234, 56, 7)
    assert any("Bemerkung" in h for h in hinweise)


def test_doppelte_dateien(tmp_path):
    kopf = [
        "Datum",
        "Messplatz",
        "Fahrtrichtung",
        "Fahrzeuge gesamt",
        "bis 15 km/h",
        "über 15 km/h",
    ]
    z = [dt.datetime(2021, 1, 5), "Krefelder Straße", "Laurensberg", 500, 20, 2]
    a = _xlsx(tmp_path / "a.xlsx", [kopf, z])
    b = _xlsx(tmp_path / "b.xlsx", [kopf, z])
    df, hinweise = aachen.lies_alle([a, b])
    assert len(df) == 1
    assert any("doppelte" in h for h in hinweise)


def test_lage_im_messplatz():
    assert aachen._lage("Trierer Straße / Kalkbergstraße") == (
        "Trierer Straße", "kreuzung", "Kalkbergstraße", None
    )  # fmt: skip
    assert aachen._lage("Krefelder Straße") == ("Krefelder Straße", "keine", None, None)
