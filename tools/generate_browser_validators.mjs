/** Offline pinned Ajv standalone compilation; never imported by browser code. */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const root = new URL("../", import.meta.url);
const packageRoot = new URL("packages/contracts/typescript/", root);
const require = createRequire(new URL("package.json", packageRoot));
const Ajv2020 = require("ajv/dist/2020.js").default;
const addFormats = require("ajv-formats").default;
const standaloneCode = require("ajv/dist/standalone/index.js").default;
const { _ } = require("ajv/dist/compile/codegen/index.js");
const names = [
  "SessionCreate",
  "RevisionCommand",
  "Error",
  "DeveloperCapability",
  "BrowserCsrf",
  "StepUpProof",
  "HelpCreateIntent",
  "LoginStart",
  "LoginIntent",
  "LoginCallback",
  "BrowserSession",
  "Empty",
  "StepUpStart",
  "Ceremony",
  "CeremonyConfirm",
  "HelpCreate",
  "HelpView",
  "HelpAuthorityRequest",
  "FreshHelpAuthority",
  "Signal",
  "SignalAck",
  "StaticManifest",
  "StaticPublish",
  "CommandResult",
];
const raw = readFileSync(new URL("src/schema.json", packageRoot));
const schema = JSON.parse(raw);
const ajv = new Ajv2020({
  strict: true,
  strictTypes: false,
  allErrors: false,
  code: { source: true },
});
addFormats(ajv);
ajv.addKeyword({
  keyword: "x-decimalMaximum",
  type: "string",
  schemaType: "string",
  errors: false,
  code(context) {
    const { data, schema: maximum } = context;
    // Identical canonical decimal semantics, expressed through Ajv CodeGen so
    // standalone output has no runtime closure or Function-constructor fallback.
    context.fail(
      _`typeof ${data} !== "string" || ${data}.length === 0 || /[^0-9]/.test(${data}) || (${data}.length > 1 && ${data}[0] === "0") || ${data}.length > 19 || BigInt(${data}) > BigInt(${maximum})`,
    );
  },
});
ajv.addSchema(schema);
const exports = Object.fromEntries(
  names.map((name) => [name, `${schema.$id}#/$defs/${name}`]),
);
const sourceHash = createHash("sha256").update(raw).digest("hex");
const header = `/* Generated offline by tools/generate_browser_validators.mjs; do not edit.\nSchema SHA256 ${sourceHash}; Ajv ${require("ajv/package.json").version}; ajv-formats ${require("ajv-formats/package.json").version}. */\n`;
const outputs = new Map([
  [
    new URL("src/validators.generated.cjs", packageRoot),
    header + standaloneCode(ajv, exports) + "\n",
  ],
  [
    new URL("src/validators.generated.d.cts", packageRoot),
    header +
      "declare const validators: Record<string, (value: unknown) => boolean>;\nexport = validators;\n",
  ],
]);
const check = process.argv.includes("--check");
if (process.argv.slice(2).some((argument) => argument !== "--check"))
  throw new Error("Only --check is supported");
for (const [target, expected] of outputs) {
  if (check) {
    if (readFileSync(target, "utf8") !== expected)
      throw new Error(`Standalone validator drift: ${fileURLToPath(target)}`);
  } else writeFileSync(target, expected);
}
process.stdout.write(
  `Browser validators ${check ? "match" : "generated from"} the pinned schema (${names.length} public contracts).\n`,
);
