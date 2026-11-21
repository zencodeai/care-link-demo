# Recovery browser verification

`pnpm exec playwright test --config tests/e2e/recovery/playwright.config.ts`

Owns Vite loopback4199 and dedicated pinned Chromium WS loopback31909/imp09-001. `PLAYWRIGHT_WS_ENDPOINT` and `IMP09_BROWSER_OUTPUT` select explicitly reserved alternatives. Default output `/private/tmp/care-link-imp09-browser`.

This harness uses synthetic route fixtures. It proves bilingual rendering, keyboard actions, semantic/axe checks at1280/640px, exact command identity, expiry handling and authority-loss cleanup. It does not prove server authorization, real identity ceremonies, network quarantine or live generation cutover. Those require integrated backend evidence. Human language, visual and screen-reader review remains deferred_until_after_IMP10.
