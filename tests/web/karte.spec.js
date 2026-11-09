// Die Karte im Browser: lädt ohne Fehler, Filter ändern die Zahlen, Fenster, Link-Zustand.
// Die Fälle suchen sich die Tests aus den Kartendaten selbst (keine festen Messstellen).
import { test, expect } from "@playwright/test";
import { erwarteKeineFehler, freiePunkt, kartendaten, oeffneKarte, warteAufKarte, zahl } from "./helpers.js";

test("Karte lädt ohne Fehler und zeichnet Messstellen", async ({ page }) => {
  const fehler = await oeffneKarte(page);
  await warteAufKarte(page);
  const n = await page.evaluate(() => window.map.querySourceFeatures("messstellen").length);
  expect(n).toBeGreaterThan(1000);
  expect(await zahl(page, "#fc-stellen")).toBeGreaterThan(1000);
  erwarteKeineFehler(fehler);
});

test("Legende zählt so viele Kontrollen, wie die Daten für Berlin haben", async ({ page }) => {
  await oeffneKarte(page);
  const manifest = await kartendaten(page, "manifest.json");
  const ohneLage = manifest.staedte.berlin.verortung.ohne_lage;
  expect(await zahl(page, "#fc-kontrollen")).toBe(manifest.staedte.berlin.kontrollen - ohneLage);
});

test("Jahresfilter verringert die Kontrollen, Zurücksetzen holt sie zurück", async ({ page }) => {
  const fehler = await oeffneKarte(page);
  const vorher = await zahl(page, "#fc-kontrollen");
  await page.locator('#f-jahre .legend-chip[data-wert="2017"]').click();
  await expect.poll(() => zahl(page, "#fc-kontrollen")).toBeLessThan(vorher);
  expect(page.url()).toContain("j=");
  await page.locator("#filter-zurueck").click();
  await expect.poll(() => zahl(page, "#fc-kontrollen")).toBe(vorher);
  erwarteKeineFehler(fehler);
});

test("Farbe nach Kontrollen: Klassen zählen alle Messstellen", async ({ page }) => {
  await oeffneKarte(page);
  await page.locator('input[name="metrik"][value="kontrollen"]').check({ force: true });
  const stellen = await zahl(page, "#fc-stellen");
  const summe = await page.evaluate(() =>
    [...document.querySelectorAll("#klassen .count-badge")].reduce((s, el) => s + Number(el.textContent.replace(/\./g, "")), 0)
  );
  expect(summe).toBe(stellen);
  expect(page.url()).toContain("m=kontrollen");
});

test("Klick auf eine Messstelle zeigt alle ihre Kontrollen", async ({ page }) => {
  const fehler = await oeffneKarte(page, "/index.html#14.00/52.50000/13.40000");
  const p = await freiePunkt(page, "p.n >= 2 && p.g === 1");
  await page.mouse.click(p.x, p.y);
  const fenster = page.locator(".maplibregl-popup-content");
  await expect(fenster).toContainText("Kontrollen");
  const zeilen = await fenster.locator(".pop-liste tbody tr").count();
  expect(zeilen).toBeGreaterThanOrEqual(2);
  expect(page.url()).toMatch(/&s=B\d+/);
  erwarteKeineFehler(fehler);
});

test("Link mit Zustand stellt Ansicht, Filter und Fenster wieder her", async ({ page }) => {
  await oeffneKarte(page);
  const stellen = await kartendaten(page, "messstellen.json");
  const kontrollen = await kartendaten(page, "kontrollen.json");
  const fk = (f) => kontrollen.felder.indexOf(f);
  // eine Messstelle mit einer Kontrolle bei Tempo 50 – die bleibt mit t=30,50 sichtbar
  const k = kontrollen.zeilen.find((z) => z[fk("tempo")] === 50 && z[fk("stelle")] != null);
  const zeile = stellen.zeilen[k[fk("stelle")]];
  const id = zeile[0];
  await oeffneKarte(page, `/index.html#15.00/${zeile[3]}/${zeile[2]}&m=stunde&t=30,50&s=${id}`);
  await expect(page.locator('input[name="metrik"][value="stunde"]')).toBeChecked();
  await expect(page.locator('#f-tempo .legend-chip[data-wert="80"] input')).not.toBeChecked();
  await expect(page.locator(".maplibregl-popup-content")).toBeVisible();
  expect(page.url()).toContain(`s=${id}`);
});

test("Methode & Quellen nennt Quellen und Lizenzen aus dem Manifest", async ({ page }) => {
  await oeffneKarte(page);
  await page.locator("#methode-auf").click();
  const d = page.locator("#methode");
  await expect(d).toBeVisible();
  await expect(d).toContainText("Polizei Berlin");
  await expect(d).toContainText("Stadt Aachen");
  await expect(d).toContainText("ODbL");
});

test("Aachen-Knopf fliegt nach Aachen und zählt Aachener Kontrollen", async ({ page }) => {
  await oeffneKarte(page);
  const manifest = await kartendaten(page, "manifest.json");
  await page.locator('.stadt-btn[data-stadt="aachen"]').click();
  await expect(page.locator('.stadt-btn[data-stadt="aachen"]')).toHaveClass(/is-active/, { timeout: 20_000 });
  await expect.poll(() => zahl(page, "#fc-kontrollen")).toBe(manifest.staedte.aachen.kontrollen - manifest.staedte.aachen.verortung.ohne_lage);
});

test("Stadt ohne Anteil (Köln): der Knopf schaltet auf „je Kontrolle“ statt alles grau", async ({ page }) => {
  await oeffneKarte(page);
  const manifest = await kartendaten(page, "manifest.json");
  const [code, s] = Object.entries(manifest.staedte).find(([, x]) => x.kontrollen > 0 && x.anteil_alle_gezaehlt === 0);
  await expect(page.locator('input[name="metrik"][value="anteil"]')).toBeChecked();
  await page.locator(`.stadt-btn[data-stadt="${code}"]`).click();
  await expect(page.locator('input[name="metrik"][value="jekontrolle"]')).toBeChecked();
  await expect.poll(() => page.url()).toContain("m=jekontrolle");
  await expect(page.locator(`.stadt-btn[data-stadt="${code}"]`)).toHaveClass(/is-active/, { timeout: 20_000 });
  await expect.poll(() => zahl(page, "#fc-kontrollen")).toBe(s.kontrollen - s.verortung.ohne_lage);
  await page.locator("#methode-auf").click();
  await expect(page.locator("#methode")).toContainText(s.quelle.bereitsteller);
});
