// @vitest-environment node
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { disclosures } from "../../apps/web/src/manual/disclosures";

it("binds browser acknowledgement to the exact server disclosure bytes", () => {
  const server: unknown = JSON.parse(
    readFileSync("config/demo/imp03/disclosures.json", "utf8"),
  );
  expect(disclosures).toEqual(server);
  for (const artifact of Object.values(disclosures)) {
    expect(artifact.text.trim().split(/\s+/).length).toBeLessThanOrEqual(60);
    expect(
      createHash("sha256").update(artifact.text, "utf8").digest("hex"),
    ).toBe(artifact.digest);
  }
});
