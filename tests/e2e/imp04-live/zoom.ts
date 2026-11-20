import { expect } from "@playwright/test";
import { renderedFrame, type Actor } from "./browser";
import { type Observations } from "./cases";
import { textFor } from "../../../apps/web/src/plans/messages";

/** Read-only native viewport evidence: CSS or pinch scaling never counts as zoom. */
async function metrics(actor: Actor) {
  return actor.page.evaluate(() => ({
    device_pixel_ratio: window.devicePixelRatio,
    css_width: window.innerWidth,
    css_height: window.innerHeight,
    outer_width: window.outerWidth,
    outer_height: window.outerHeight,
    visual_scale: window.visualViewport?.scale ?? null,
    document_width: document.documentElement.scrollWidth,
  }));
}

export async function nativeZoom(
  actor: Actor,
  locale: "en-CA" | "fr-CA",
  observations: Observations,
): Promise<void> {
  await actor.page.bringToFront();
  await actor.page.keyboard.press("Control+Digit0");
  const settle = () => renderedFrame(actor.page, "native_zoom_frame");
  await settle();
  const before = await metrics(actor);
  try {
    // Chrome's standard ladder:100,110,125,150,175,200 percent.
    for (let i = 0; i < 5; i++) {
      await actor.page.keyboard.press("Control+Equal");
      await settle();
    }
    const after = await metrics(actor);
    const supported =
      Math.abs(after.device_pixel_ratio / before.device_pixel_ratio - 2) <
        0.05 &&
      Math.abs(after.css_width / before.css_width - 0.5) < 0.03 &&
      Math.abs(after.outer_width - before.outer_width) < 2 &&
      after.visual_scale === before.visual_scale;
    if (!supported) {
      observations.push({
        case: "Q08-native-zoom",
        slot: actor.slot,
        locale,
        status: "not_run",
        reason:
          "Native browser accelerators did not expose a verified200percent desktop zoom",
        before,
        after,
        css_or_pinch_zoom_substituted: false,
        manual_zoom_review_required: true,
      });
      return;
    }
    const check = actor.page.getByRole("button", {
      name: textFor(locale).check,
      exact: true,
    });
    await check.scrollIntoViewIfNeeded();
    await check.focus();
    await expect(check).toBeFocused();
    await expect(check).toBeVisible();
    await actor.page.locator("#plans-id").scrollIntoViewIfNeeded();
    await actor.page.locator("#plans-id").focus();
    await actor.page.keyboard.press("Tab");
    expect(
      await actor.page.evaluate(() => document.activeElement?.tagName),
    ).toBe("BUTTON");
    observations.push({
      case: "Q08-native-zoom",
      slot: actor.slot,
      locale,
      status: "passed",
      native_desktop_zoom_percent: 200,
      native_keyboard_focus_and_controls_reachable: true,
      before,
      after,
      css_or_pinch_zoom_substituted: false,
      human_visual_or_screen_reader_review_claimed: false,
    });
  } finally {
    await actor.page.keyboard.press("Control+Digit0");
    await settle();
    const restored = await metrics(actor);
    expect(restored.device_pixel_ratio).toBeCloseTo(
      before.device_pixel_ratio,
      2,
    );
    expect(restored.css_width).toBeCloseTo(before.css_width, 0);
  }
}
