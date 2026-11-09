// Verträge zwischen Seite, Kartendaten und Repo – ohne Browser, laufen in Sekunden.
import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const WURZEL = fileURLToPath(new URL("../../", import.meta.url));
const lies = (pfad) => readFileSync(WURZEL + pfad, "utf-8");
const json = (pfad) => JSON.parse(lies(pfad));

test("index.html lädt genau die MapLibre-Version, gegen die getestet wird", () => {
  const getestet = json("node_modules/maplibre-gl/package.json").version;
  const geladen = [...lies("index.html").matchAll(/maplibre-gl@([^/"]+)\//g)].map((m) => m[1]);
  expect(geladen.length).toBe(2); // CSS + JS
  for (const v of geladen) expect(v, "Version in index.html und package.json angleichen").toBe(getestet);
});

test("Prüfsummen (SRI) in index.html passen zu den MapLibre-Dateien dieser Version", () => {
  // Wer die Version hebt, rechnet die integrity-Werte neu:
  //   openssl dgst -sha384 -binary node_modules/maplibre-gl/dist/maplibre-gl.js | openssl base64 -A
  const html = lies("index.html");
  for (const datei of ["maplibre-gl.js", "maplibre-gl.css"]) {
    const soll = "sha384-" + createHash("sha384").update(readFileSync(WURZEL + "node_modules/maplibre-gl/dist/" + datei)).digest("base64");
    const tag = html.split("\n").find((z) => z.includes(`/dist/${datei}"`));
    expect(tag, datei).toContain(`integrity="${soll}"`);
  }
});

test("Alle Dateien aus dem Manifest liegen im Repo", () => {
  const manifest = json("pipeline/data/karte/manifest.json");
  for (const datei of Object.values(manifest.dateien)) {
    expect(existsSync(WURZEL + "pipeline/data/karte/" + datei), datei).toBe(true);
  }
});

test("Feldnamen der Kartendaten sind die, die js/daten.js erwartet", () => {
  const stellen = json("pipeline/data/karte/messstellen.json");
  const kontrollen = json("pipeline/data/karte/kontrollen.json");
  expect(stellen.felder).toEqual(["id", "stadt", "lon", "lat", "strasse", "methode", "lage", "osm_maxspeed", "hinweis"]);
  expect(kontrollen.felder).toEqual(["stelle", "tag", "beginn", "dauer", "tempo", "messungen", "ueber", "stufe1", "stufe2", "fahrverbote", "alle", "richtung", "ort", "grenze"]);
  expect(stellen.methoden).toEqual(["hausnummer", "abschnitt", "kreuzung", "anschlussstelle", "strasse"]);
});

test("Datenlage: jede Stadt mit Stand, den das Manifest kennt, und den Feldern für js/datenlage.js", () => {
  const manifest = json("pipeline/data/karte/manifest.json");
  const dl = json("pipeline/data/karte/" + manifest.dateien.datenlage);
  expect(dl.features.length).toBeGreaterThan(5);
  for (const f of dl.features) {
    const p = f.properties;
    expect(Object.keys(manifest.datenlage_stand), p.kommune).toContain(p.stand);
    expect(Object.keys(p)).toEqual(
      expect.arrayContaining(["kommune", "land", "stand", "stadt", "kontrollen", "was", "anfrage", "recht", "links", "kontakt"])
    );
    if (p.stadt) expect(manifest.staedte[p.stadt].kontrollen, p.kommune).toBe(p.kontrollen);
  }
  expect(existsSync(WURZEL + "docs/DATENLAGE.md")).toBe(true);
});
