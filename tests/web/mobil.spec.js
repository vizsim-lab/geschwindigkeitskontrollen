// Handy: Legende als zugeklapptes Bottom-Sheet, aufklappbar.
import { test, expect } from "@playwright/test";
import { erwarteKeineFehler, oeffneKarte } from "./helpers.js";

test("Legende startet zugeklappt und klappt auf", async ({ page }) => {
  const fehler = await oeffneKarte(page);
  const legende = page.locator("#legende");
  await expect(legende).toHaveClass(/collapsed/);
  await expect(page.locator("#klassen")).toBeHidden();
  await page.locator("#legende-auf").click();
  await expect(page.locator("#klassen")).toBeVisible();
  erwarteKeineFehler(fehler);
});
