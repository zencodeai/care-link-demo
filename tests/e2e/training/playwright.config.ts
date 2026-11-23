import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

const output =
  process.env.IMP10_TRAINING_BROWSER_OUTPUT ??
  "/private/tmp/care-link-imp10-training-browser";

const endpoint = process.env.IMP10_TRAINING_BROWSER_WS_ENDPOINT;
const executablePath = process.env.IMP10_TRAINING_BROWSER_PATH;

export default defineConfig({
  testDir: ".",
  testMatch: "training.spec.ts",
  workers: 1,
  retries: 0,
  outputDir: resolve(output, "artifacts"),
  reporter: [
    ["line"],
    ["json", { outputFile: resolve(output, "results.json") }],
  ],
  webServer: {
    command:
      "pnpm --filter @care-link/web exec vite --host 127.0.0.1 --port 4200 --strictPort --force",
    url: "http://127.0.0.1:4200",
    reuseExistingServer: false,
    env: { VITE_OIDC_ORIGIN: "https://identity.qualification.localhost" },
  },
  use: {
    baseURL: "http://127.0.0.1:4200",
    browserName: "chromium",
    ...(endpoint
      ? {
          connectOptions: {
            wsEndpoint: endpoint,
            exposeNetwork: "<loopback>",
            headers: {
              "x-playwright-launch-options": JSON.stringify({
                executablePath: "/opt/chrome-for-testing/chrome",
                headless: true,
              }),
            },
          },
        }
      : executablePath
        ? { launchOptions: { executablePath } }
        : {}),
    trace: "off",
    screenshot: "off",
    video: "off",
    viewport: { width: 1280, height: 960 },
  },
});
