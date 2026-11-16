"use strict";
const { spawn } = require("node:child_process");
// Private loopback automation capability. Launch options are supplied only by
// the trusted test harness, selecting the pinned Chrome for Testing executable.
const child = spawn(process.execPath, [
  "/opt/playwright-core/cli.js", "run-server", "--host", "0.0.0.0",
  "--port", "29900", "--path", "/" + process.env.CARE_LINK_REVIEW_WS_PATH.replace(/^\/+/, ""),
  "--max-clients", "1", "--unsafe",
], { stdio: "inherit" });
process.on("SIGTERM", () => child.kill("SIGTERM"));
child.on("exit", code => process.exit(code ?? 1));
