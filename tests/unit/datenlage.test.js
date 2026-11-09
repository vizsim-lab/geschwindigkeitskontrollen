// Browserlose Tests der Ebene „Datenlage je Stadt“ (js/datenlage.js).
import { test } from "node:test";
import assert from "node:assert/strict";

import * as DL from "../../js/datenlage.js";

const FC = {
  type: "FeatureCollection",
  features: [
    { properties: { kommune: "Berlin", stand: "in_karte" } },
    { properties: { kommune: "Duisburg", stand: "geliefert" } },
    { properties: { kommune: "Konstanz", stand: "offen" } },
    { properties: { kommune: "Stuttgart", stand: "kandidat" } },
    { properties: { kommune: "Dresden", stand: "abgelehnt" } },
    { properties: { kommune: "Essen", stand: "teilweise" } },
  ],
};

test("Klassen: jeder Stand genau einmal, Unbekanntes grau", () => {
  const alle = DL.KLASSEN.flatMap((k) => k.stand);
  assert.equal(new Set(alle).size, alle.length);
  assert.equal(DL.klasse("geliefert").id, "offen");
  assert.equal(DL.klasse("gibtsnicht").farbe, DL.GRAU);
});

test("Farbausdruck nennt jeden Stand und endet grau", () => {
  const a = DL.farbAusdruck();
  assert.equal(a[0], "match");
  for (const k of DL.KLASSEN) for (const s of k.stand) assert.equal(a[a.indexOf(s) + 1], k.farbe);
  assert.equal(a.at(-1), DL.GRAU);
});

test("Zählen je Klasse und Legende", () => {
  assert.deepEqual(DL.zaehle(FC), { in_karte: 1, offen: 2, kandidat: 1, sonst: 2 });
  const html = DL.legendeHtml(FC);
  assert.equal((html.match(/<li>/g) || []).length, DL.KLASSEN.length);
  assert.match(html, /offen oder auf Anfrage herausgegeben<\/span><span class="count-badge">2/);
});

test("Fenster: Stadt in der Karte mit Hinzoomen, Anfrage und Belegen", () => {
  const html = DL.detailHtml(
    {
      kommune: "Berlin",
      land: "BE",
      stand: "in_karte",
      kontrollen: 37123,
      was: "temporäre Kontrollen",
      empfehlung: "Neu fragen",
      kontakt: { fds: "https://fragdenstaat.de/behoerden/?q=Polizei+Berlin", fds_suche: true },
      anfrage: { betreff: "Betreff", text: "Bitte <alles>" },
      recht: "Berliner IFG",
      links: [{ titel: "FragDenStaat", url: "https://fragdenstaat.de/anfrage/x/" }],
    },
    { in_karte: "in der Karte" }
  );
  assert.match(html, /37\.123 Kontrollen in der Karte – hinzoomen/);
  assert.match(html, /data-kopieren/);
  assert.match(html, /Bitte &lt;alles&gt;/); // escaped
  assert.match(html, /Behörde auf FragDenStaat suchen/);
  assert.match(html, /Berliner IFG\. Keine Rechtsberatung\./);
  assert.match(html, /issues\/new\?template=daten-melden\.yml/);
});

test("Fenster: Stadt ohne Daten zeigt Lage statt Hinzoomen", () => {
  const html = DL.detailHtml({ kommune: "Dresden", stand: "abgelehnt", was: "abgelehnt", situation: "Aufwand", links: [] });
  assert.doesNotMatch(html, /hinzoomen/);
  assert.match(html, /<div class="detail-abschnitt">Lage<\/div><p class="detail-text">Aufwand/);
  assert.doesNotMatch(html, /Anfragetext/);
});
