import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
const output = resolve(
  "doc/IMP/slices/IMP-05-reviewed-simulated-referral/sessions/001-implementation/evidence/browser",
);
export default defineConfig({
  testDir: ".",
  testMatch: "referral.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120000,
  expect: { timeout: 15000 },
  outputDir: resolve(output, "artifacts"),
  reporter: [
    ["line"],
    ["json", { outputFile: resolve(output, "playwright-results.json") }],
  ],
  webServer: {
    command:
      "pnpm --filter @care-link/web exec vite --host 127.0.0.1 --port 5175 --strictPort",
    url: "http://127.0.0.1:5175",
    reuseExistingServer: false,
    timeout: 30000,
    env: { VITE_OIDC_ORIGIN: "https://identity.qualification.localhost" },
  },
  use: {
    baseURL: "http://127.0.0.1:5175",
    browserName: "chromium",
    ignoreHTTPSErrors: false,
    connectOptions: {
      wsEndpoint: "ws://127.0.0.1:30905/",
      exposeNetwork: "<loopback>",
      headers: {
        "x-playwright-launch-options": JSON.stringify({
          executablePath: "/opt/chrome-for-testing/chrome",
          headless: true,
        }),
      },
    },
    actionTimeout: 15000,
    navigationTimeout: 30000,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
