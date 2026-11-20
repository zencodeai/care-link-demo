# IMP-05 isolated Chromium qualification

This suite runs the real React application and Chromium against **mocked synthetic authenticated API and provider responses**. It does not establish deployed identity, MFA, PostgreSQL, TLS or service-mesh behavior. The independent backend integration suite supplies its own real PostgreSQL evidence.

The primary starts the existing isolated Playwright server at `ws://127.0.0.1:30905/`; this config launches its own loopback Vite server on port5175 and uses the existing `/opt/chrome-for-testing/chrome` binary through that server. No live demo origin is touched. Identity-provider navigation is absent from these deterministic fixtures.

Run `pnpm exec playwright test -c tests/e2e/referral/playwright.config.ts`. Results and attached synthetic accessibility/reflow summaries are written beneath the current IMP-05 session's `evidence/browser`. EN/FR worker, client and receiver cases exercise keyboard activation/focus, exact review/consent binding, honest uncertain/partial outcomes, axe WCAG2A/AA+2.1AA checks and 1280/640px layout. Native 200% zoom and human language, visual and screen-reader reviews are not established; human review remains `deferred_until_after_IMP10`.
