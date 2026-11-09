# SPDX-License-Identifier: AGPL-3.0-or-later
"""fetch fragt jede Stadt mit Katalogen – `ckan` (Aachen) oder `kataloge` (Köln, Bonn)."""

from kontrollen import cli, fetch


def test_fetch_fragt_alle_katalogstaedte(monkeypatch):
    gefragt = []
    monkeypatch.setattr(fetch, "berlin", lambda: [])
    monkeypatch.setattr(fetch, "aachen", lambda neu=False: [])
    monkeypatch.setattr(fetch, "ckan_dateien", lambda s, neu=False: gefragt.append(s) or [])
    cli.fetch_cmd(berlin_=False, aachen_=False, andere=True, mit_osm=False, neu=False)
    assert "koeln" in gefragt and "bonn" in gefragt
