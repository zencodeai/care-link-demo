import AxeBuilder from "@axe-core/playwright";
import { expect } from "@playwright/test";
import { labels } from "../../../apps/web/src/review/labels";
import { ActorPage } from "./browser";
import { slots, type Row, type Slot } from "./config";

const tags = ["wcag2a", "wcag2aa", "wcag21aa"];

export async function reviewPageAccessibility(
  actors: Record<Slot, ActorPage>,
  observations: Row[],
  checkpoint: (stage: string) => void,
) {
  for (const slot of slots) {
    const actor = actors[slot];
    const english = labels("en-CA");
    const french = labels("fr-CA");
    checkpoint(`run_1_review_accessibility_${slot}_en`);
    await actor.assertVisibleIdentity();
    await expect(
      actor.page.getByRole("heading", { name: english.title, exact: true }),
    ).toBeVisible();
    for (const locale of ["en-CA", "fr-CA"] as const) {
      if (locale === "fr-CA") {
        checkpoint(`run_1_review_accessibility_${slot}_fr`);
        await actor.page
          .getByLabel(english.language, { exact: true })
          .selectOption("fr-CA");
        await expect(
          actor.page.getByRole("heading", { name: french.title, exact: true }),
        ).toBeVisible();
      }
      const text = labels(locale);
      await expect(actor.page).toHaveTitle(`${text.title} · ${slot}`);
      await expect(actor.page.locator("html")).toHaveAttribute("lang", locale);
      await expect(
        actor.page.locator("header").getByText(actor.actor.account, {
          exact: true,
        }),
      ).toBeVisible();
      await expect(actor.button(text.signOut)).toBeVisible();
      await actor.current();
      const result = await new AxeBuilder({ page: actor.page })
        .withTags(tags)
        .analyze();
      const summary = {
        slot,
        locale,
        tags,
        violations: result.violations.map((violation) => ({
          rule: violation.id,
          impact: violation.impact,
          affected_nodes: violation.nodes.length,
        })),
        passed_rule_count: result.passes.length,
        incomplete_rule_count: result.incomplete.length,
        status:
          result.violations.length === 0 && result.passes.length > 0
            ? "passed"
            : "failed",
      };
      observations.push(summary);
      expect(
        summary.passed_rule_count,
        "Axe actually evaluated review rules",
      ).toBeGreaterThan(0);
      expect(summary.violations, "Actual review-page WCAG violations").toEqual(
        [],
      );
    }
    checkpoint(`run_1_review_locale_restore_${slot}`);
    await actor.page
      .getByLabel(french.language, { exact: true })
      .selectOption("en-CA");
    await expect(
      actor.page.getByRole("heading", { name: english.title, exact: true }),
    ).toBeVisible();
    await expect(actor.page).toHaveTitle(`${english.title} · ${slot}`);
    await expect(actor.page.locator("html")).toHaveAttribute("lang", "en-CA");
    await actor.assertVisibleIdentity();
    observations.push({
      slot,
      visible_language_roundtrip: ["en-CA", "fr-CA", "en-CA"],
      exact_actor_retained: true,
      status: "passed",
    });
  }
}
