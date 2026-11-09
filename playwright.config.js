// Browser-Tests der Karte (tests/web/). Die Karte ist eine statische Seite ohne Build:
// getestet wird, was GitHub Pages aus der Repo-Wurzel ausliefert, über einen einfachen
// Python-Webserver. 127.0.0.1 statt localhost (IPv4); belegter Port = Fehler.
// Lokal ohne heruntergeladenen Browser: PW_CHANNEL=chrome nimmt das installierte Chrome.
import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.PW_PORT) || 4190;
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "tests/web",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  workers: process.env.CI ? 2 : undefined,
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: BASE_URL,
    trace: process.env.CI ? "on-first-retry" : "off",
    screenshot: "only-on-failure",
    ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}),
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 } }, testIgnore: /mobil\.spec\.js/ },
    { name: "handy", use: { ...devices["Pixel 7"] }, testMatch: /mobil\.spec\.js/ },
  ],
  webServer: {
    command: `python3 -m http.server ${PORT} --bind 127.0.0.1`,
    url: `${BASE_URL}/index.html`,
    reuseExistingServer: false,
    stderr: "ignore",
    timeout: 30_000,
  },
});
