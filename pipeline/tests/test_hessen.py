# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hessen: Butzbach (Monatstabellen des Ordnungsbehördenbezirks, mit Uhrzeit, ohne Tempo) und
Weiterstadt (Monatstabellen „Statistik GemOBB“, mit Tempo, ohne Uhrzeit); dazu der Katalog
`art: seite` (Links einer Webseite)."""

import pytest

from kontrollen import butzbach, dokumente, fetch, weiterstadt

# --- Weiterstadt ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, strasse, nr, quer, richtung",
    [
        ("Gräfenhäuser Straße 17, FR Gräfenhausen", "Gräfenhäuser Straße", "17", None, "Gräfenhausen"),
        ("Darmstädter Landstraße HH Nr. 55 FR L3113", "Darmstädter Landstraße", "55", None, "L3113"),
        ("Riedstraße Höhe Nr. 16, FR Riedbahnstraße", "Riedstraße", "16", None, "Riedbahnstraße"),
        ("Beuneweg Höhe Hausnummer 13, FR Triftweg", "Beuneweg", "13", None, "Triftweg"),
        ("B42, Höhe Vor den Löserbecken, FR Darmstadt", "B 42", None, "Vor den Löserbecken", "Darmstadt"),
        ("L 3113 Höhe Weiterstädter Weg, FR Mörfelden- Walldorf",
         "L 3113", None, "Weiterstädter Weg", "Mörfelden- Walldorf"),
        ("L3113 Höhe Hannemannsgarten 1, FR MöWa", "L 3113", None, "Hannemannsgarten", "MöWa"),
        ("K 165 Höhe Firma Gede Türenwerk Fr Gräfenhausen",
         "K 165", None, "Firma Gede Türenwerk", "Gräfenhausen"),
        ("Rudolf-Diesel-Straße Höhe Feuerwehr, FR. Brunnenweg",
         "Rudolf-Diesel-Straße", None, "Feuerwehr", "Brunnenweg"),
        ("B 42 FR Darmstadt", "B 42", None, None, "Darmstadt"),
        ("Am Blindgraben 4c, FR Brunnenweg", "Am Blindgraben", "4c", None, "Brunnenweg"),
    ],
)  # fmt: skip
def test_weiterstadt_messstelle(text, strasse, nr, quer, richtung):
    m = weiterstadt.messstelle(text)
    assert (m["strasse"], m["hausnummer"], m["quer1"], m["richtung_roh"]) == (
        strasse, nr, quer, richtung,
    )  # fmt: skip
    assert m["lage_art"] == ("kreuzung" if quer else "keine")


def test_strassennummer():
    assert weiterstadt.strassennummer("B42") == "B 42"
    assert weiterstadt.strassennummer("L 3113") == "L 3113"
    assert weiterstadt.strassennummer("K165") == "K 165"
    assert weiterstadt.strassennummer("Bahnstraße") is None
    assert weiterstadt.strassennummer("B42 Höhe X") is None


def test_weiterstadt_tabelle(monkeypatch, tmp_path):
    tabelle = [
        ["Geschwindigkeitskontrollen Januar 2025", None, None, None, None],
        ["Datum", "Straße, Hausnummer, Fahrtrichtung", "zulässige\nHöchst-\ngeschwindigkeit",
         "durchfahrene\nFahrzeuge", "davon mit\nGeschwindigkeits-\nüberschreitung"],
        ["", None, None, None, None],
        ["02.01.2025", "B42, Höhe Vor den Löserbecken, FR Darmstadt", "70", "1667", "57"],
        ["", "", "", "", ""],
        ["07.01.2025", "Gräfenhäuser Straße 17, FR Gräfenhausen", "70", "259", "0"],
        ["07.01.2025", "Gräfenhäuser Straße 17, FR Gräfenhausen", "70", "1.312", "4"],
    ]  # fmt: skip
    monkeypatch.setattr(dokumente, "tabellen", lambda pfad: tabelle)
    f = tmp_path / "geschwindigkeitskontrollen-januar-2025__Statistik_GemOBB_Januar_2025.pdf"
    f.write_bytes(b"%PDF-")
    df, b = weiterstadt.lies_alle([f, f])  # dieselbe Datei zweimal: jede Zeile einmal
    assert len(df) == 3 and b["doppelt"] == 3 and df["id"].is_unique
    assert df["messungen"].tolist() == [1667, 259, 1312]
    assert df["tempo"].tolist() == [70, 70, 70]
    assert df["ueberschreitungen"].tolist() == [57, 0, 4]  # 0 bleibt 0: so steht es da
    assert df["alle_gezaehlt"].all() and df["beginn"].isna().all()
    assert df["id"].iloc[2] == df["id"].iloc[1] + "-2"
    assert set(df["quelle"]) == {"geschwindigkeitskontrollen-januar-2025"}


# --- Butzbach ------------------------------------------------------------------------------

KOPF = ["Tag", "von…", "…bis", "Gesamtstun\nden", "Gesamt\nFahrzeuge", "Verwarnungen",
        "Bußgelder", "Verstöße in\n%", "Messstelle"]  # fmt: skip


@pytest.mark.parametrize(
    "text, bezirk, strasse, nr, quer",
    [
        ("Butzbach/Griedel, L3134 ggü Rockenberger Str.", "Griedel", "L 3134", None, "Rockenberger Str"),
        ("Butzbach, In der Alböhn ggü in Höhe Grundstück Am Dreispitz 16-18",
         "Butzbach", "In der Alböhn", None, "Am Dreispitz"),
        ("Butzbach/Griedel, Schlagweg, Neben Alte Hauptsr.", "Griedel", "Schlagweg", None, "Alte Hauptstr"),
        ("Butzbach, Oberer Lachenweg 19 / Erlebnislandschaft Vicus Romanus",
         "Butzbach", "Oberer Lachenweg", "19", None),
        ("Wölfersheim, Hauptstraße / Kiga Löwenherz", "Wölfersheim", "Hauptstraße", None, "Kiga Löwenherz"),
        ("Butzbach, Ludwigstr. Ecke Kleeberger Str. 6", "Butzbach", "Ludwigstr.", None, "Kleeberger Str"),
        ("Butzbach/Fauerbach, Ostheimer Str. ggü Weidbrunnenstraße 2A",
         "Fauerbach", "Ostheimer Str.", None, "Weidbrunnenstraße"),
        ("Butzbach, Tepler Str. / Seedammweg", "Butzbach", "Tepler Str.", None, "Seedammweg"),
        ("Wölfersheim/Geisenheim, B455 / Seestr. In Höhe 60-62", "Geisenheim", "B 455", None, "Seestr"),
        ("Butzbach/Pohl-Göns, Windhofstraße Höhe Hs. Nr. 21", "Pohl-Göns", "Windhofstraße", "21", None),
        ("Münzenberg/Trais, Wetterstr. 21", "Trais", "Wetterstr.", "21", None),
    ],
)  # fmt: skip
def test_butzbach_messstelle(text, bezirk, strasse, nr, quer):
    m = butzbach.messstelle(text)
    assert (m["bezirk_roh"], m["strasse"], m["hausnummer"], m["quer1"]) == (
        bezirk,
        strasse,
        nr,
        quer,
    )


def test_butzbach_tabelle(monkeypatch, tmp_path):
    tabelle = [
        KOPF,
        ["01.04.2026", "6:45", "10:10", "03:25", "953", "37", "5", "4,4%",
         "Butzbach/Griedel, L3134 ggü Rockenberger Str."],
        ["09.04..2026", "11:50", "13:45", "01:55", "307", "27", "1", "9,1%",
         "Butzbach, Ludwigstr. Ecke Kleeberger Str. 6"],
        ["21.04.2026", "22:30", "01:10", "", "1.226", "8", "3", "4,9%", "Butzbach, Taunustr 45"],
        ["", "", "", "00:00", "", "0", "0", "#DIV/0!", ""],  # leere Vorlagezeile
        [None, None, None, "54:06", "13.348", "555", "46", "", None],  # Summe
    ]  # fmt: skip
    monkeypatch.setattr(dokumente, "tabellen", lambda pfad: tabelle)
    f = tmp_path / "geschwindigkeitsmessungen-im-april-2026__sb_oa-messung-2604.pdf"
    f.write_bytes(b"%PDF-")
    df, b = butzbach.lies_alle([f])
    assert len(df) == 3 and df["id"].is_unique
    assert df["datum"].tolist() == ["2026-04-01", "2026-04-09", "2026-04-21"]
    assert df["beginn"].tolist() == ["06:45", "11:50", "22:30"]
    assert df["dauer_min"].tolist() == [205, 115, 160]  # ohne Gesamtstunden: über Mitternacht
    assert df["messungen"].tolist() == [953, 307, 1226]
    assert df["ueberschreitungen"].tolist() == [42, 28, 11]  # Verwarnungen + Bußgelder
    assert df["alle_gezaehlt"].all() and df["tempo"].isna().all()
    assert df["id"].iloc[0].startswith("U2026-04-01-0645-")


# --- Katalog: Links einer Seite --------------------------------------------------------------


def test_seite_als_katalog_folgt_beitraegen_und_blaettert(monkeypatch):
    basis = "https://stadt.example/themen/messungen/"
    seiten = {
        basis: [
            ("https://stadt.example/b/messungen-im-mai-2026/", "Geschwindigkeitsmessungen im Mai 2026"),
            ("https://stadt.example/themen/messungen/page/2/", "← Ältere Beiträge"),
            ("https://stadt.example/wp-content/uploads/formular.pdf", "Formular"),
        ],
        "https://stadt.example/themen/messungen/page/2/": [
            ("https://stadt.example/b/messungen-im-april-2026/", "Geschwindigkeitsmessungen im April 2026"),
        ],
        "https://stadt.example/b/messungen-im-mai-2026/": [
            ("https://stadt.example/wp-content/uploads/sb_oa-messung-2605.pdf", "Herunterladen"),
            ("https://stadt.example/wp-content/uploads/sb_oa-messung-2605.pdf#x",
             "Geschwindigkeitsmessungen im Mai 2026"),
            ("https://stadt.example/b/messungen-im-april-2026/", "Vorheriger Beitrag"),
        ],
        "https://stadt.example/b/messungen-im-april-2026/": [
            ("https://stadt.example/wp-content/uploads/sb_oa-messung-2604.pdf", "Herunterladen"),
        ],
    }  # fmt: skip
    geholt = []
    monkeypatch.setattr(fetch, "seiten_links", lambda url: geholt.append(url) or seiten[url])
    k = {
        "art": "seite",
        "url": basis,
        "dateien": r"/uploads/sb_oa-messung-\d{4}\.pdf$",
        "folge": r"/b/messungen-im-",
        "blaettern": r"/page/\d+/$",
    }
    ds = fetch._seite_als_katalog(k)
    assert sorted(geholt) == sorted(seiten)  # jede Seite einmal
    titel = {d["resources"][0]["url"].rsplit("/", 1)[1]: d["title"] for d in ds}
    assert titel == {
        "sb_oa-messung-2605.pdf": "Geschwindigkeitsmessungen im Mai 2026",
        # auf der Beitragsseite nur „Herunterladen“: es gilt der Link der Übersicht
        "sb_oa-messung-2604.pdf": "Geschwindigkeitsmessungen im April 2026",
    }
    cfg = {"titel_muster": "(?i)messung", "stadt_muster": "stadt", "formate": ["PDF"]}
    t = fetch.treffer(ds, cfg, basis)
    assert {d["url"] for d in t} == {
        "https://stadt.example/b/messungen-im-mai-2026/",
        "https://stadt.example/b/messungen-im-april-2026/",
    }


def test_seite_als_katalog_mit_titel(monkeypatch):
    seite = "https://www.weiterstadt.example/geschwindigkeitsmessungen/index.php"
    monkeypatch.setattr(
        fetch,
        "seiten_links",
        lambda url: [
            ("https://www.weiterstadt.example/_media/Statistik_GemOBB_Januar_2025.pdf?m=17&", "Januar 2025"),
            ("https://www.weiterstadt.example/_media/Satzung.pdf", "Satzung"),
        ],
    )  # fmt: skip
    k = {"art": "seite", "url": seite, "dateien": r"(?i)Statistik_GemOBB_.*\.pdf",
         "titel": "Geschwindigkeitskontrollen"}  # fmt: skip
    (d,) = fetch._seite_als_katalog(k)
    assert d["title"] == "Geschwindigkeitskontrollen Januar 2025"
    assert d["name"] == "geschwindigkeitskontrollen-januar-2025"
    assert d["resources"][0]["format"] == "PDF" and d["seite"] == seite
    r = {**d["resources"][0], "format": "PDF"}
    assert fetch._dateiname(d["name"], r) == (
        "geschwindigkeitskontrollen-januar-2025__Statistik_GemOBB_Januar_2025.pdf"
    )
