// Gemeinsame Helfer für die Browser-Tests.
//
// Getestet wird die Seite, wie Pages sie ausliefert – mit zwei Ausnahmen, damit die Tests nicht
// am Netz hängen:
//   - MapLibre kommt aus node_modules statt von unpkg (vertrag.spec.js prüft, dass es dieselbe
//     Version mit denselben Prüfsummen ist).
//   - Die Hintergrundkarte (OpenFreeMap) ist ein leerer Stil, Photon und Rasterkacheln
//     antworten leer: getestet wird unsere Ebene darüber, nicht die Kacheln.
import { expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const MAPLIBRE = fileURLToPath(new URL("../../node_modules/maplibre-gl/dist/", import.meta.url));
const UNPKG = /^https:\/\/unpkg\.com\/maplibre-gl@[^/]+\/dist\/(maplibre-gl\.(?:js|css))$/;
const LEERER_STIL = JSON.stringify({
  version: 8,
  sources: {},
  layers: [{ id: "hintergrund", type: "background", paint: { "background-color": "#f2f3f0" } }],
});

/** Seite öffnen und warten, bis die App bereit ist (<body data-bereit="1">). Liefert die JS-Fehler. */
export async function oeffneKarte(page, pfad = "/index.html") {
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(`pageerror: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && fehler.push(m.text()));
  await page.route(UNPKG, (route) => {
    const datei = UNPKG.exec(route.request().url())[1];
    return route.fulfill({
      body: readFileSync(MAPLIBRE + datei),
      contentType: datei.endsWith(".css") ? "text/css" : "text/javascript",
    });
  });
  await page.route("https://tiles.openfreemap.org/**", (route) =>
    route.fulfill({ body: LEERER_STIL, contentType: "application/json" })
  );
  await page.route(/^https:\/\/(tile\.openstreetmap\.org|server\.arcgisonline\.com)\//, (route) => route.fulfill({ status: 204 }));
  await page.route("https://photon.komoot.io/**", (route) =>
    route.fulfill({ body: JSON.stringify({ type: "FeatureCollection", features: [] }), contentType: "application/json" })
  );
  // erst weg von der Seite: ein Link, der sich nur im Anker unterscheidet, lüde sonst nicht neu
  await page.goto("about:blank");
  await page.goto(pfad);
  await page.waitForSelector("body[data-bereit='1']", { timeout: 45_000 });
  return fehler;
}

export function erwarteKeineFehler(fehler) {
  expect(fehler, "JS-Fehler auf der Seite").toEqual([]);
}

/** Kartendatei so laden, wie die Seite sie lädt. */
export function kartendaten(page, datei) {
  return page.evaluate((d) => fetch(`pipeline/data/karte/${d}`).then((r) => r.json()), datei);
}

/** Warten, bis die Karte gezeichnet hat (GeoJSON verarbeitet MapLibre im Hintergrund). */
export async function warteAufKarte(page) {
  await page.evaluate(
    () =>
      new Promise((fertig) => {
        const m = window.map;
        if (m.loaded() && m.areTilesLoaded() && !m.isMoving()) return fertig();
        m.once("idle", fertig);
        setTimeout(fertig, 15_000);
      })
  );
}

/** Zahl aus der Legende ("1.234" -> 1234). */
export async function zahl(page, selektor) {
  const t = await page.locator(selektor).textContent();
  return Number(t.replace(/\./g, ""));
}

/** Bildschirmpunkt einer gezeichneten Messstelle, die frei liegt (nicht unter Legende/Panel). */
export async function freiePunkt(page, bedingung = "true") {
  await warteAufKarte(page);
  const p = await page.evaluate((bed) => {
    const passt = new Function("p", `return ${bed};`);
    const frei = (x, y) => document.elementFromPoint(x, y)?.tagName === "CANVAS";
    const f = window.map
      .queryRenderedFeatures({ layers: ["punkte"] })
      .filter((x) => passt(x.properties))
      .map((x) => ({ q: window.map.project(x.geometry.coordinates), i: x.properties.i }))
      .find(({ q }) => frei(q.x, q.y) && frei(q.x - 6, q.y - 6) && frei(q.x + 6, q.y + 6));
    return f ? { x: f.q.x, y: f.q.y, i: f.i } : null;
  }, bedingung);
  expect(p, "kein freier Punkt gezeichnet").not.toBeNull();
  return p;
}
