import { type Observations } from "./cases";

/** A phase reports its own evidence; another phase's proof is never invented. */
export function phaseCoverage(
  phase: string,
  observations: Observations,
  actorCount = 9,
) {
  const required: Record<string, string[]> = {
    normal: [
      "Q03/A01",
      "Q05/A01",
      "Q04/A01",
      "Q03-worker-conflict",
      "A02-revocation",
      "A02-real-expiry",
      "Q09",
      "Q09-draft",
    ],
    "normal-continue": ["A02-real-expiry", "Q09"],
    "reload-only": ["Q09-reload-only"],
    "report-ui": ["Q05-report-ui"],
    "pending-ui": ["Q09-pending-ui"],
    "manual-regression": ["Q09-manual-regression"],
    directory: ["Q06", "A06"],
    lifecycle: ["Q07"],
    accessibility: ["Q08"],
    race: ["A03-revoke-before-policy", "A03-expire-before-final-output"],
    "absent-race": ["A04"],
    "authority-loss": ["A03-grantor-authority-loss"],
    dependency: ["A08"],
    delegation: ["A05"],
    "delegation-expired": ["A05-expired"],
    signin: ["Q02"],
  };
  const expected =
    phase === "all"
      ? [
          ...new Set([
            ...(required.normal ?? []),
            ...(required.directory ?? []),
            "Q07",
            "Q08",
          ]),
        ]
      : (required[phase] ?? []);
  const expectedCount: Record<string, number> = {
    "Q05/A01": 2,
    "Q05-report-ui": 4,
    Q06: 2,
    Q08: 8,
    A08: 3,
    Q02: actorCount,
  };
  const checks = expected.map((name) => {
    const actual = observations.filter(
      (item) => item.case === name && item.status === "passed",
    ).length;
    const count = expectedCount[name] ?? 1;
    return {
      check: name,
      expected_passed_observations: count,
      actual_passed_observations: actual,
      completed: actual >= count,
    };
  });
  const notRun = checks
    .filter((item) => !item.completed)
    .map(
      (item) =>
        `${item.check}: phase evidence incomplete (${item.actual_passed_observations}/${item.expected_passed_observations} passed observations)`,
    );
  if (["all", "accessibility"].includes(phase)) {
    const native = observations.filter(
      (item) => item.case === "Q08-native-zoom" && item.status === "passed",
    ).length;
    if (native < 8)
      notRun.push(
        `Native200percent desktop zoom: ${native}/8 verified actor/locale observations; human completion required where unsupported`,
      );
    notRun.push(
      "Manual screen-reader and human visual accessibility review require separate actual evidence",
    );
  }
  if (
    ["all", "normal", "lifecycle", "pending-ui", "absent-race"].includes(phase)
  )
    notRun.push(
      "Coordinator read-only DB effects, review counts and lifecycle metadata are recorded outside browser phase",
    );
  return {
    checks,
    notRun,
    scope:
      "Only this phase; independent network/trust/DB/recovery/manual-human evidence is not inferred",
  };
}
