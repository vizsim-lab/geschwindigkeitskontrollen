// Browserlose Tests der reinen Module (node --test). Laufen in Sekunden.
import { test } from "node:test";
import assert from "node:assert/strict";

import * as D from "../../js/daten.js";
import * as P from "../../js/permalink.js";

// zwei Messstellen in Berlin (genau / nur Straße), eine in Aachen
const STELLEN = {
  felder: ["id", "stadt", "lon", "lat", "strasse", "methode", "lage", "osm_maxspeed"],
  staedte: ["aachen", "berlin"],
  methoden: ["hausnummer", "abschnitt", "kreuzung", "anschlussstelle", "strasse"],
  zeilen: [
    ["B00000", 1, 13.4, 52.5, "Hauptstraße", 0, "Nr. 10 · zw. A u. B", "50"],
    ["B00001", 1, 13.5, 52.6, "Eckallee", 4, "", null],
    ["A00002", 0, 6.1, 50.8, "Trierer Straße", 4, "Trierer Straße", "50"],
  ],
};
const T = (iso) => (Date.parse(iso + "T00:00:00Z") - Date.parse("2000-01-01T00:00:00Z")) / 86400000;
const KONTROLLEN = {
  felder: ["stelle", "tag", "beginn", "dauer", "tempo", "messungen", "ueber", "stufe1", "stufe2", "fahrverbote", "alle", "richtung", "ort"],
  tag0: "2000-01-01",
  richtungen: [""],
  orte: [""],
  zeilen: [
    [0, T("2018-03-01"), 480, 240, 50, 1000, 100, 90, 10, 1, 1, 0, 0],
    [0, T("2019-05-02"), 540, 120, 30, 800, 80, 70, 5, 0, 1, 0, 0],
    [1, T("2017-07-07"), 1320, 180, 80, 200, 200, 150, 50, 10, 0, 0, 0], // nur zu schnelle erfasst
    [2, T("2021-04-01"), null, null, null, 400, 21, 20, 1, null, 1, 0, 0],
    [null, T("2018-02-02"), 600, 60, 30, 10, 1, 1, 0, 0, 1, 0, 0], // ohne Lage
  ],
};
const daten = D.entpacke(STELLEN, KONTROLLEN);
const ALLE = { jahre: null, tempo: null, methoden: null };

test("entpacke rechnet Jahr, Tempoklasse und Stadt vor", () => {
  assert.equal(daten.kontrollen[0].jahr, 2018);
  assert.equal(daten.kontrollen[0].tempoKlasse, "50");
  assert.equal(daten.kontrollen[1].tempoKlasse, "30");
  assert.equal(daten.kontrollen[3].tempoKlasse, "u");
  assert.equal(daten.kontrollen[3].stadt, "aachen");
  assert.equal(daten.stellen[1].genau, false);
});

test("verdichte summiert je Messstelle, ohne Lage fällt weg", () => {
  const agg = D.verdichte(daten, ALLE);
  assert.equal(agg.size, 3);
  const a = agg.get(0);
  assert.deepEqual([a.n, a.mess, a.ueber, a.minuten, a.fv], [2, 1800, 180, 360, 1]);
  assert.equal(D.wert(a, "anteil"), 10);
  assert.equal(D.wert(a, "stunde"), 30);
});

test("Anteil nur, wo alle Fahrzeuge gezählt sind; je Stunde nur mit Dauer", () => {
  const agg = D.verdichte(daten, ALLE);
  assert.equal(D.wert(agg.get(1), "anteil"), null); // Messungen = Überschreitungen
  assert.equal(D.wert(agg.get(2), "stunde"), null); // Aachen: keine Dauer
  assert.equal(D.wert(agg.get(2), "fahrverbote"), null);
  assert.equal(D.wert(agg.get(2), "anteil"), 5.25);
});

test("Filter nach Jahr, Tempo und Verortung", () => {
  assert.equal(D.verdichte(daten, { ...ALLE, jahre: new Set([2019]) }).get(0).n, 1);
  assert.equal(D.verdichte(daten, { ...ALLE, tempo: new Set(["30"]) }).size, 1);
  const genau = D.verdichte(daten, { ...ALLE, methoden: new Set(["hausnummer"]) });
  assert.deepEqual([...genau.keys()], [0]);
});

test("Klassen und ihre Beschriftung", () => {
  assert.equal(D.klasse(null, "anteil"), -1);
  assert.equal(D.klasse(1.9, "anteil"), 0);
  assert.equal(D.klasse(2, "anteil"), 1);
  assert.equal(D.klasse(25, "anteil"), 4);
  assert.deepEqual(D.klassenText("anteil"), ["unter 2 %", "2–5 %", "5–10 %", "10–20 %", "ab 20 %"]);
  assert.deepEqual(D.klassenText("kontrollen"), ["1", "2–3", "4–9", "10–29", "ab 30"]);
  assert.deepEqual(D.klassenText("fahrverbote"), ["0", "1", "2–5", "6–20", "ab 21"]);
});

test("zusammenfassung zählt je Filterwert unter den übrigen Filtern", () => {
  const f = { ...ALLE, jahre: new Set([2018]) };
  const z = D.zusammenfassung(daten, D.verdichte(daten, f), "anteil", f);
  assert.equal(z.kontrollen, 1);
  assert.equal(z.ohneLage, 1);
  assert.deepEqual(z.jeJahr, { 2017: 1, 2018: 1, 2019: 1, 2021: 1 });
  assert.equal(z.jeTempo["50"], 1);
});

test("punkte liefert GeoJSON mit Klasse und Genauigkeit", () => {
  const g = D.punkte(daten, D.verdichte(daten, ALLE), "anteil");
  assert.equal(g.features.length, 3);
  const p = g.features.find((f) => f.id === 1);
  assert.deepEqual(p.properties, { i: 1, n: 1, k: -1, g: 0 });
});

test("Formatieren", () => {
  assert.equal(D.zahl(12345), "12.345");
  assert.equal(D.zahl(5.25, 1), "5,3");
  assert.equal(D.uhrzeit(1320), "22:00");
  assert.equal(D.dauerText(150), "2 h 30 min");
  assert.equal(D.datumText(daten.kontrollen[0].datum), "01.03.2018");
});

test("Permalink: hin und zurück", () => {
  const z = {
    zoom: 13.2, lat: 52.51234, lon: 13.40123, metrik: "stunde",
    jahre: new Set([2019, 2017]), tempo: new Set(["50", "30"]),
    methoden: new Set(["strasse", "hausnummer"]), stelle: "B01234",
  };
  const a = P.schreibe(z);
  assert.equal(a, "13.20/52.51234/13.40123&m=stunde&j=2017,2019&t=30,50&v=h,x&s=B01234");
  const r = P.lies("#" + a);
  assert.equal(r.metrik, "stunde");
  assert.deepEqual([...r.jahre], [2017, 2019]);
  assert.deepEqual([...r.methoden].sort(), ["hausnummer", "strasse"]);
  assert.equal(r.stelle, "B01234");
  assert.deepEqual(P.lies("#quatsch&m=nix&t=999"), { tempo: new Set() });
  assert.equal(P.schreibe({ zoom: 10, lat: 52.5, lon: 13.4, metrik: "anteil", jahre: null, tempo: null, methoden: null }), "10.00/52.50000/13.40000");
});
