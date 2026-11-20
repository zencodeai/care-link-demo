import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
import { execFileSync } from "node:child_process";
import { isIP } from "node:net";
import { evidenceDirectory, readConfig } from "./config";
const config = readConfig();
const output = evidenceDirectory();
const directMain = process.env.CARE_LINK_IMP04_E2E_DIRECT_MAIN;
if (directMain && directMain !== "plans-002")
  throw new Error("Exact independent target route selection required");
const route = directMain
  ? (JSON.parse(
      execFileSync(
        resolve(".venv/bin/python"),
        ["-m", "tools.imp04_verification.browser_route"],
        { encoding: "utf8", timeout: 10000, stdio: ["ignore", "pipe", "pipe"] },
      ),
    ) as { address: string; browser_id: string; ingress_id: string })
  : null;
if (
  route &&
  (isIP(route.address) !== 4 ||
    !route.address.startsWith("172.29.47.") ||
    !/^[0-9a-f]{64}$/.test(route.browser_id) ||
    !/^[0-9a-f]{64}$/.test(route.ingress_id))
)
  throw new Error("Exact inspected ingress route required");
process.env.CARE_LINK_IMP04_E2E_MAIN_ROUTE = route?.address ?? "broker";
export default defineConfig({
  testDir: ".",
  testMatch: "live.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 1_200_000,
  expect: { timeout: 20_000 },
  outputDir: resolve(output, "artifacts"),
  reporter: [
    ["line"],
    ["json", { outputFile: resolve(output, "playwright-results.json") }],
  ],
  use: {
    browserName: "chromium",
    ignoreHTTPSErrors: false,
    connectOptions: {
      wsEndpoint: config.endpoint,
      exposeNetwork: "*.localhost,<loopback>",
      headers: {
        "x-playwright-launch-options": JSON.stringify({
          executablePath: "/opt/chrome-for-testing/chrome",
          headless: true,
          ...(route
            ? {
                args: [
                  `--host-resolver-rules=MAP plans.localhost ${route.address}`,
                  "--proxy-bypass-list=<-loopback>;plans.localhost",
                ],
              }
            : {}),
        }),
      },
    },
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
