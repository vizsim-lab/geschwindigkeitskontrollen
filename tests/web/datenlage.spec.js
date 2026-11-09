// Ebene „Datenlage je Stadt“: einschalten, Stadt anklicken, Seitenleiste, Hinzoomen.
// Die Städte kommen aus datenlage.json (keine festen Namen außer der Wahl „eine Stadt mit
// Anfragetext“ und „eine Stadt in der Karte“).
import { test, expect } from "@playwright/test";
import { erwarteKeineFehler, kartendaten, oeffneKarte, warteAufKarte } from "./helpers.js";

async function punktVon(page, kommune) {
  await warteAufKarte(page);
  return page.evaluate((k) => {
    const f = window.__app.datenlage.features.find((x) => x.properties.kommune === k);
    const q = window.map.project(f.geometry.coordinates);
    return { x: q.x, y: q.y };
  }, kommune);
}

test("Datenlage einschalten zeigt Deutschland und schreibt d=1 in den Link", async ({ page }) => {
  const fehler = await oeffneKarte(page);
  const box = page.locator("#toggle-datenlage");
  await expect(box).not.toBeChecked();
  await box.check();
  await expect.poll(() => page.evaluate(() => window.map.getZoom())).toBeLessThan(8);
  await expect.poll(() => page.evaluate(() => window.map.getLayoutProperty("datenlage-kreis", "visibility"))).toBe("visible");
  await expect.poll(() => page.url()).toContain("d=1");
  const dl = await kartendaten(page, "datenlage.json");
  const summe = await page.evaluate(() =>
    [...document.querySelectorAll("#datenlage-legende .count-badge")].reduce((s, el) => s + Number(el.textContent.replace(/\./g, "")), 0)
  );
  expect(summe).toBe(dl.features.length);
  erwarteKeineFehler(fehler);
});

// Zoom 8: die Punkte benachbarter Städte (Duisburg, Krefeld, Essen) liegen dort nicht übereinander
const bei = (f) => `/index.html#8.00/${f.geometry.coordinates[1]}/${f.geometry.coordinates[0]}&d=1`;

test("Klick auf eine Stadt ohne Daten zeigt Stand, Anfragetext und Belege", async ({ page }) => {
  await oeffneKarte(page);
  const dl = await kartendaten(page, "datenlage.json");
  const ziel = dl.features.find((f) => !f.properties.kontrollen && f.properties.anfrage);
  const fehler = await oeffneKarte(page, bei(ziel));
  const p = await punktVon(page, ziel.properties.kommune);
  await page.mouse.click(p.x, p.y);
  const leiste = page.locator("#datenlage-detail");
  await expect(leiste).toBeVisible();
  await expect(leiste.locator(".detail-titel")).toHaveText(ziel.properties.kommune);
  await expect(leiste.locator(".anfrage-text")).toHaveValue(ziel.properties.anfrage.text);
  await expect(leiste.locator(".detail-hinweise a").first()).toHaveAttribute("href", ziel.properties.links[0].url);
  await leiste.locator("[data-schliessen]").click();
  await expect(leiste).toBeHidden();
  erwarteKeineFehler(fehler);
});

test("Stadt in der Karte: Hinzoomen fliegt zu ihren Messstellen", async ({ page }) => {
  await oeffneKarte(page);
  const dl = await kartendaten(page, "datenlage.json");
  const ziel = dl.features.find((f) => f.properties.kontrollen > 0);
  const fehler = await oeffneKarte(page, bei(ziel));
  const p = await punktVon(page, ziel.properties.kommune);
  await page.mouse.click(p.x, p.y);
  const knopf = page.locator("#datenlage-detail [data-hinzoomen]");
  await expect(knopf).toContainText("Kontrollen in der Karte");
  await knopf.click();
  await expect(page.locator("#datenlage-detail")).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.map.getZoom()), { timeout: 20_000 }).toBeGreaterThan(10);
  erwarteKeineFehler(fehler);
});
