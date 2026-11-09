// SPDX-License-Identifier: AGPL-3.0-or-later
// Fenster einer Messstelle: was fehlt, steht nicht als 0 da (Köln nennt keine gemessenen Fahrzeuge).
import { test } from "node:test";
import assert from "node:assert/strict";

import * as D from "../../js/daten.js";
import { stelleHtml } from "../../js/popup.js";

const STELLEN = {
  felder: ["id", "stadt", "lon", "lat", "strasse", "methode", "lage", "osm_maxspeed", "hinweis"],
  staedte: ["berlin", "koeln"],
  methoden: ["hausnummer", "abschnitt", "kreuzung", "anschlussstelle", "strasse"],
  zeilen: [
    ["B1", 0, 13.4, 52.5, "Hauptstraße", 0, "Nr. 10", "50", null],
    ["K1", 1, 6.95, 50.94, "Amsterdamer Straße", 0, "Nr. 80", "50", null],
  ],
};
const T = (iso) => (Date.parse(iso + "T00:00:00Z") - Date.parse("2000-01-01T00:00:00Z")) / 86400000;
const KONTROLLEN = {
  felder: ["stelle", "tag", "beginn", "dauer", "tempo", "messungen", "ueber", "stufe1", "stufe2", "fahrverbote", "alle", "richtung", "ort", "grenze"],
  tag0: "2000-01-01",
  richtungen: ["", "stadtauswärts"],
  orte: [""],
  zeilen: [
    [0, T("2019-05-02"), 540, 120, 50, 800, 80, 70, 10, 0, 1, 0, 0, 20],
    [1, T("2023-03-01"), null, null, 50, null, 30, 28, 2, null, 0, 1, 0, 20],
    [1, T("2024-06-11"), null, null, 50, null, 15, 15, 0, null, 0, 1, 0, 20],
  ],
};
const MANIFEST = { staedte: { berlin: { label: "Berlin" }, koeln: { label: "Köln" } } };
const daten = D.entpacke(STELLEN, KONTROLLEN);
const ALLE = { jahre: null, tempo: null, methoden: null };
const agg = D.verdichte(daten, ALLE);
const fenster = (i, voll = true) =>
  stelleHtml({ daten, stelle: daten.stellen[i], agg: agg.get(i), metrik: "jekontrolle", filter: ALLE, manifest: MANIFEST, voll });

test("Köln: keine „0 Fahrzeuge“, dafür Verstöße je Kontrolle; Liste ohne Spalte Fzg.", () => {
  const h = fenster(1);
  assert.doesNotMatch(h, /Gemessen/);
  assert.match(h, /Zu schnell je Kontrolle<\/td><td>23</);
  assert.doesNotMatch(h, /Fzg\./);
  assert.match(h, /Alle 2 Kontrollen/);
});

test("Berlin: gemessene Fahrzeuge und Spalte Fzg. bleiben", () => {
  const h = fenster(0);
  assert.match(h, /Gemessen<\/td><td>800 Fahrzeuge/);
  assert.match(h, /Fzg\./);
  assert.doesNotMatch(h, /Zu schnell je Kontrolle/);
});
