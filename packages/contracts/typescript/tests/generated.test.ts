// @vitest-environment node
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { Script, createContext } from "node:vm";
import { describe, expect, it } from "vitest";

const path = resolve(
  "packages/contracts/typescript/src/validators.generated.cjs",
);
const source = readFileSync(path, "utf8");
function callable(value: unknown): value is (input: unknown) => unknown {
  return typeof value === "function";
}

describe("precompiled browser validators under disabled string code generation", () => {
  it("loads and validates bounds and closed shapes without Function/eval", () => {
    const require = createRequire(path);
    const exports: Record<string, unknown> = {};
    const context = createContext(
      {
        exports,
        require: (name: string): unknown => {
          if (
            ![
              "ajv/dist/runtime/ucs2length",
              "ajv/dist/runtime/equal",
              "ajv-formats/dist/formats",
            ].includes(name)
          )
            throw new Error("Unexpected standalone runtime dependency");
          const dependency: unknown = require(name);
          return dependency;
        },
      },
      { codeGeneration: { strings: false, wasm: false } },
    );
    new Script(source, { filename: "validators.generated.cjs" }).runInContext(
      context,
    );
    const revision = exports.RevisionCommand;
    const csrf = exports.BrowserCsrf;
    if (!callable(revision) || !callable(csrf))
      throw new Error("Missing public standalone validators");
    expect(revision({ expected_revision: "9223372036854775807" })).toBe(true);
    expect(revision({ expected_revision: "9223372036854775808" })).toBe(false);
    expect(revision({ expected_revision: "1\n" })).toBe(false);
    expect(revision({ expected_revision: "1", role: "operator" })).toBe(false);
    expect(csrf({ csrf_token: "a".repeat(32) })).toBe(true);
    expect(csrf({ csrf_token: "a".repeat(32), role: "operator" })).toBe(false);
    expect(source).not.toMatch(/\bnew\s+Function\s*\(|\beval\s*\(/);
  });
});
