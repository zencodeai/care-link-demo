import { describe, expect, it } from "vitest";
import {
  ContractError,
  parseCapability,
  parseContract,
  validateContract,
} from "../src/index";

const session = {
  tags: { environment: "demo", population: "synthetic" },
  participant_kind: "pid",
  jurisdiction: null,
  locale: "en-CA",
  channel: "web",
  persona_id: null,
  fixture_id: null,
};
const capability = {
  contract_version: "dev-1",
  status: "developer_only",
  tags: { environment: "demo", population: "synthetic" },
  participant_admission: false,
  business_operations: "unavailable",
  contract_validation: true,
};

describe("strict contracts", () => {
  it.each(["0", "1", "9223372036854775807"])(
    "accepts canonical revision %s",
    (revision) => {
      expect(() =>
        validateContract("RevisionCommand", { expected_revision: revision }),
      ).not.toThrow();
    },
  );
  it.each(["9223372036854775808", "01", "-1", "1.0", "1\n", 1, true, null])(
    "rejects noncanonical or overflowing revision %s",
    (revision) => {
      expect(() =>
        validateContract("RevisionCommand", { expected_revision: revision }),
      ).toThrow(ContractError);
    },
  );
  it("accepts a closed synthetic session shape without performing an operation", () => {
    expect(parseContract("SessionCreate", JSON.stringify(session))).toEqual(
      session,
    );
  });
  it("rejects an unknown nested key and real population", () => {
    expect(() =>
      validateContract("SessionCreate", {
        ...session,
        tags: { ...session.tags, authority: true },
      }),
    ).toThrow(ContractError);
    expect(() =>
      validateContract("SessionCreate", {
        ...session,
        tags: { ...session.tags, population: "real" },
      }),
    ).toThrow(ContractError);
  });
  it.each([
    '{"expected_revision":"1","expected_revision":"2"}',
    '{"expected_revision":"1","expected_revisio\\u006e":"2"}',
    '{"expected_revision":"1",}',
    '{/*comment*/"expected_revision":"1"}',
    '{"expected_revision":NaN}',
    '{"expected_revision":1e400}',
    '{"expected_revision":"\\ud800"}',
    '{"expected_revision":"1","\\udfff":true}',
  ])("rejects malformed or ambiguous JSON: %s", (raw) => {
    expect(() => parseContract("RevisionCommand", raw)).toThrow(ContractError);
  });
  it("rejects non-JSON values and cycles instead of serializing them", () => {
    expect(() =>
      validateContract("RevisionCommand", { expected_revision: undefined }),
    ).toThrow(ContractError);
    const value: { expected_revision: unknown } = { expected_revision: null };
    value.expected_revision = value;
    expect(() => validateContract("RevisionCommand", value)).toThrow(
      ContractError,
    );
  });
  it("rejects unsupported contract names", () => {
    expect(() => parseContract("ConsentGrant", "{}")).toThrow(ContractError);
  });
  it("validates capabilities before exposing a typed result", () => {
    expect(
      parseCapability(JSON.stringify(capability)).participant_admission,
    ).toBe(false);
    expect(() =>
      parseCapability(
        JSON.stringify({ ...capability, participant_admission: true }),
      ),
    ).toThrow(ContractError);
    expect(() =>
      parseCapability(JSON.stringify({ ...capability, role: "worker" })),
    ).toThrow(ContractError);
  });
});
