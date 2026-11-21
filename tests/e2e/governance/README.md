# IMP-08 browser verification

Run `pnpm exec playwright test --config tests/e2e/governance/playwright.config.ts` with the owned pinned Chromium fixture. Exclusive Vite loopback4188, Chromium WS loopback30908/imp08-001; override `PLAYWRIGHT_WS_ENDPOINT` and `IMP08_BROWSER_OUTPUT` when reserving other isolated resources. Default output: `/private/tmp/care-link-imp08-browser`.

These route fixtures verify EN/FR operator/security/governance/auditor workspaces, exact artifact change context, desired/current epochs, pending commit retry identity, coupled metric disclosure, contract rejection, expired-auth clearing, keyboard activation, axe and 1280/640px layout. Backend authorization, signed provenance, PostgreSQL final guards and actual independent identity require separate backend/integration evidence. Fixtures are synthetic and do not grant authority or establish human review. Human usability, visual, screen-reader and language review: deferred_until_after_IMP10.
