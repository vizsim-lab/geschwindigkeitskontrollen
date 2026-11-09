# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kleine Gemeinden: Schonungen (Monatsberichte als Text, auch Word) und Oberderdingen
(Quartalstabellen; beide Richtungen in einer Zählung)."""

import zipfile

import pytest

from kontrollen import dokumente, oberderdingen, schonungen

BERICHT = """Verkehrsstatistik; Geschwindigkeitsmessungen in der Gemeinde Schonungen
Messstelle Mainberg, St2447, Mainleite / Bereich Hs.-Nr. 28
Zulässige Geschwindigkeit: 50 km/h
Messzeitpunkt: Dienstag, 10.03.2026, 11:54 Uhr – 16:54 Uhr
Anzahl der Fahrzeuge: 3193
Verstöße: 34
Überschreitung: 25 innerhalb bis 10 km/h über zul. Geschwindigkeit
8 innerhalb, 11-15 km/h über zul. Geschwindigkeit
1 innerhalb, 31-40 km/h über zul. Geschwindigkeit
 Messstelle Reichmannshausen, SW 4, Herrenseestraße / Bereich Einm. Alter
Mühlweg
Zulässige Geschwindigkeit: 50 km/h
Messzeitpunkt: Montag,28.11.2022, 15:29 Uhr – 018:00 Uhr
Anzahl Fahrzeuge: 33
Verstöße: 0
Messstelle Mainberg, St2447, Mainleite, Bereich Einm. Steinbergstr. Hs.-Nr. 42
Zulässige Geschwindigkeit: 50 km/h
Messzeitpunkt: Dienstag, 20.01.2026, 07:00 Uhr – 12:00 Uhr
Anzahl der Fahrzeuge: 1843
Verstöße: 2
Überschreitung: 2 innerhalb bis 10 km/h über zul. Geschwindigkeit
Messzeitpunkt: Freitag, 30.01.2026, 06.12 Uhr – 11:12 Uhr
Anzahl der Fahrzeuge: 1883, Verstöße: 21
Überschreitung: 20 innerhalb bis 10 km/h über zul. Geschwindigkeit
1 mit 21 – 25 km/h über zulässiger Geschwindigkeit
"""


def test_schonungen_messungen_aus_dem_bericht():
    ms = [m for b in schonungen.bloecke(BERICHT) for m in schonungen.messungen(b)]
    assert len(ms) == 4  # die dritte Messstelle zweimal gemessen
    a, b, c, d = ms
    assert (a["tempo"], a["messungen"], a["ueberschreitungen"], a["stufe1"], a["stufe2"]) == (
        50, 3193, 34, 33, 1,
    )  # fmt: skip
    assert (a["beginn"].strftime("%d.%m.%Y %H:%M"), a["dauer_min"]) == ("10.03.2026 11:54", 300)
    assert b["ort"] == "Reichmannshausen, SW 4, Herrenseestraße / Bereich Einm. Alter Mühlweg"
    assert (b["dauer_min"], b["ueberschreitungen"], b["stufe1"]) == (151, 0, 0)  # „018:00“
    assert c["ort"] == d["ort"] and d["beginn"].day == 30
    assert (d["messungen"], d["ueberschreitungen"], d["stufe1"], d["stufe2"]) == (1883, 21, 20, 1)


def test_schonungen_summe_fehlt_und_klassen_passen_nicht():
    b = """X, Hofheimer Straße, Bereich Hs.-Nr. 55 - 57
Zulässige Geschwindigkeit: 50 km/h
Messzeitpunkt: Donnerstag, 26.06.2025, 12:57 Uhr – 17:57 Uhr
Anzahl Fahrzeuge: 505
Verstöße: 7 innerhalb bis 10 km/h über zul. Geschwindigkeit
3 innerhalb 11-15 km/h über zul. Geschwindigkeit
"""
    m = schonungen.messungen(b)[0]
    assert (m["ueberschreitungen"], m["stufe1"], m["stufe2"]) == (10, 10, 0)
    b2 = b.replace("Verstöße: 7 innerhalb", "Verstöße: 12\nÜberschreitung: 7 innerhalb")
    m2 = schonungen.messungen(b2)[0]
    assert (m2["ueberschreitungen"], m2["stufe1"]) == (12, None)  # 7 + 3 ≠ 12: ohne Stufen


@pytest.mark.parametrize(
    "text, teil, strasse, nr, quer",
    [
        ("Mainberg, St2447, Mainleite / Bereich Hs.-Nr. 28", "Mainberg", "Mainleite", "28", None),
        ("St2266, Hofheimer Straße/Höhe Hausnummer 55", None, "Hofheimer Straße", "55", None),
        ("Waldsachsen, Bucher Straße/SW 24, Bereich ggü. Hs.-Nr. 3",
         "Waldsachsen", "Bucher Straße", "3", None),
        ("Marktsteinach,St2266 Marktstein. Hauptstr./Einm. Untere Weinbergsl.",
         "Marktsteinach", "Marktstein. Hauptstr.", None, "Untere Weinbergsl"),
        ("Schonungen, ST 2447, Hauptstraße / Bereich Einm. Jahnstr. o. ggü.",
         "Schonungen", "Hauptstraße", None, "Jahnstr"),
        ("St2447, Bereich Einm. Jahnstraße oder ggü.", None, None, None, None),
    ],
)  # fmt: skip
def test_schonungen_messstelle(text, teil, strasse, nr, quer):
    m = schonungen.messstelle(text)
    assert (m["bezirk_roh"], m["strasse"], m["hausnummer"], m["quer1"]) == (teil, strasse, nr, quer)


def test_word_bericht(tmp_path):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    absaetze = "".join(f"<w:p><w:r><w:t>{z}</w:t></w:r></w:p>" for z in BERICHT.splitlines())
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>{absaetze}</w:body></w:document>'
    f = tmp_path / "bericht.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/document.xml", xml)
    df, b = schonungen.lies_alle([f, f])  # dieselbe Datei zweimal: jede Messung einmal
    assert len(df) == 4 and b["dateien"][1]["doppelt"] == 4
    assert df["alle_gezaehlt"].all() and (df["stadt"] == "schonungen").all()
    assert df["id"].is_unique


def test_oberderdingen_messstelle():
    m = oberderdingen.messstelle(
        "Oberderdingen, Großvillars, Heilbronner Straße in Höhe Einmündung Schulstraße, "
        "FR Knittlingen"
    )
    assert (m["bezirk_roh"], m["strasse"], m["quer1"], m["richtung_roh"]) == (
        "Großvillars", "Heilbronner Straße", "Schulstraße", "Knittlingen",
    )  # fmt: skip
    m = oberderdingen.messstelle(
        "Oberderdingen, Brettener Straße ggü. Hausnummer 15, FR Am Stadion"
    )
    assert (m["strasse"], m["hausnummer"], m["gegenueber"]) == ("Brettener Straße", "15", True)


def test_oberderdingen_beide_richtungen(monkeypatch, tmp_path):
    tabelle = [
        ["Datum", "Messstelle/Straße", "Festgesetzte\nGeschwindig-\nkeit", "Zahl", "Beanst."],
        ["15.01.2026", "Oberderdingen,\nFlehinger Straße 27,\nFR Hauptstraße", "30", "1762", "8"],
        ["15.01.2026", "Oberderdingen,\nFlehinger Straße 27,\nFR Brettener Straße", "30", "1762", "47"],
        ["10.01.2024", "Oberderdingen,\nBrettener Straße ggü.\nHausnummer 15,\nFR Flehinger Straße", "30", "223", "6"],
        ["10.01.2024", "Oberderdingen,\nBrettener Straße ggü.\nHausnummer 15,\nFR Am Stadion", "30", "1.324", "15"],
        # gleicher Ort, Tag und Fahrzeuge, andere Beanstandungen: zwei Kontrollen, eigene Ids
        ["22.10.2025", "Oberderdingen, Flehingen,\nSteinbrunnenstraße in Höhe\nKindergarten,\nFR Franz-von-Sickingen-Straße", "10", "22", "0"],
        ["22.10.2025", "Oberderdingen, Flehingen,\nSteinbrunnenstraße in Höhe\nKindergarten,\nFR Franz-von-Sickingen-Straße", "10", "22", "2"],
    ]  # fmt: skip
    monkeypatch.setattr(dokumente, "tabellen", lambda pfad: tabelle)
    f = tmp_path / "q.pdf"
    f.write_bytes(b"%PDF-")
    df, b = oberderdingen.lies_alle([f])
    assert len(df) == 5 and b["beide_richtungen"] == 1 and df["id"].is_unique
    beide = df[df["richtung_roh"] == "beide"].iloc[0]
    assert (beide["messungen"], beide["ueberschreitungen"]) == (1762, 55)
    assert sorted(df["messungen"].tolist()) == [22, 22, 223, 1324, 1762]
    kita = df[df["messungen"] == 22].sort_values("id")
    assert kita["ueberschreitungen"].tolist() == [0, 2]
    assert kita["id"].iloc[1] == kita["id"].iloc[0] + "-2"
    assert set(kita["richtung_roh"]) == {"Franz-von-Sickingen-Straße"}
    assert df["alle_gezaehlt"].all() and df["beginn"].isna().all()
