# Assistance browser verification

Run `pnpm exec playwright test --config tests/e2e/assistance/playwright.config.ts` with an owned pinned Chromium service at `PLAYWRIGHT_WS_ENDPOINT` (default loopback30906). Vite uses exclusive loopback5176. Evidence writes to `IMP06_BROWSER_OUTPUT` (default `/private/tmp/care-link-imp06-browser`).

These real Chromium EN/FR, keyboard, focus, axe and 1280/640px checks use synthetic browser API responses. They verify UI behavior, not deployed identity/policy/data authority, actual model outputs or human usability/screen-reader/visual/language review. Human review is deferred_until_after_IMP10. No private browser storage or real participant data is used.
