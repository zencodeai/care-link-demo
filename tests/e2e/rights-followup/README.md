# Follow-up and rights browser verification

Run `pnpm exec playwright test --config tests/e2e/rights-followup/playwright.config.ts` against an owned pinned Chromium server. Default endpoint is loopback30907/imp07-001, Vite uses exclusive loopback4187. `PLAYWRIGHT_WS_ENDPOINT` and `IMP07_BROWSER_OUTPUT` override the endpoint/output directory; output defaults to `/private/tmp/care-link-imp07-browser`.

These Chromium tests use synthetic route fixtures and validate EN/FR UI behavior, keyboard submission, exact idempotency replay, truthful cancellation and backup-pending exceptions, private data removal, 1280/640px overflow and axe. They do not qualify real identity, policy, PostgreSQL, scheduling or deletion. Human usability, screen-reader, visual and language review remains deferred_until_after_IMP10.
