// @vitest-environment node
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { parseContract } from "../../packages/contracts/typescript/src/index";

type Case = { id: string; schema: string; raw: string; valid: boolean };
const source = JSON.parse(
  readFileSync("doc/LLD/contracts/fixtures.json", "utf8"),
) as {
  fixtures: { id: string; schema: string; value: unknown; valid: boolean }[];
};
const cases: Case[] = source.fixtures
  .filter((f) =>
    ["SessionCreate", "RevisionCommand", "Error"].includes(f.schema),
  )
  .map((f) => ({ ...f, raw: JSON.stringify(f.value) }));
for (const [id, raw, valid] of [
  ["zero", '{"expected_revision":"0"}', true],
  ["max", '{"expected_revision":"9223372036854775807"}', true],
  ["overflow", '{"expected_revision":"9223372036854775808"}', false],
  ["numeric", '{"expected_revision":1}', false],
  ["leading-zero", '{"expected_revision":"01"}', false],
  ["newline", '{"expected_revision":"1\\n"}', false],
  ["duplicate", '{"expected_revision":"0","expected_revision":"1"}', false],
  [
    "escaped-duplicate",
    '{"expected_revision":"0","expected_\\u0072evision":"1"}',
    false,
  ],
  ["nan", '{"expected_revision":NaN}', false],
  ["infinity", '{"expected_revision":1e999}', false],
  ["surrogate", '{"expected_revision":"\\ud800"}', false],
  ["comment", '{/* comment */"expected_revision":"1"}', false],
  ["trailing", '{"expected_revision":"1",}', false],
  ["unknown", '{"expected_revision":"1","extra":true}', false],
] as const)
  cases.push({ id, schema: "RevisionCommand", raw, valid });
const session = source.fixtures.find((f) => f.id === "shape-SessionCreate");
if (!session) throw new Error("Missing reviewed SessionCreate fixture");
cases.push({
  id: "nested-unknown",
  schema: "SessionCreate",
  valid: false,
  raw: JSON.stringify({
    ...(session.value as object),
    tags: { environment: "demo", population: "synthetic", authority: true },
  }),
});

describe("Python / TypeScript wire parity against shared reviewed cases", () => {
  it("agrees on every expected verdict without coercion", () => {
    const python = JSON.parse(
      execFileSync(resolve(".venv/bin/python"), ["tools/contract_probe.py"], {
        input: JSON.stringify(cases),
        encoding: "utf8",
      }),
    ) as boolean[];
    expect(python).toHaveLength(cases.length);
    cases.forEach((fixture, index) => {
      let accepted = true;
      try {
        parseContract(fixture.schema, fixture.raw);
      } catch {
        accepted = false;
      }
      expect({
        id: fixture.id,
        python: python[index],
        typescript: accepted,
      }).toEqual({
        id: fixture.id,
        python: fixture.valid,
        typescript: fixture.valid,
      });
    });
  });
});
