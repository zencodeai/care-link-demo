# Identity and private-help browser surfaces

The default build retains the IMP-01 developer shell and adds the IMP-02 main-account surface. The help build is a separate entry with no core API request or startup dependency. Neither build admits participants or supplies an account role; the identity service establishes current access for every protected operation.

Configuration is fixed at build time:

| Variable             | Value                                                                               |
| -------------------- | ----------------------------------------------------------------------------------- |
| `VITE_SURFACE`       | `main` (default), or `help` for the separate help origin                            |
| `VITE_OIDC_ORIGIN`   | Exact approved HTTPS provider origin, without trailing slash                        |
| `VITE_HELP_ORIGIN`   | Exact independent HTTPS help origin; main build links to `/private-help`            |
| `VITE_STATIC_ORIGIN` | Exact independent HTTPS static origin; links to `/fallback?locale=en-CA` or `fr-CA` |

Missing or invalid origins disable the corresponding redirect/link. The help and static origins must differ from the current application origin. The browser makes private API requests only to its own origin; this does not require a foreign-origin CORS exception. Build the help bundle separately and serve it with the independently configured help BFF and its distinct OIDC client, fixed callback, and host-only Secure/HttpOnly cookie. Serve only the intended origin's bundle. The host/proxy configuration and live qualification are separate implementation evidence.

From the repository root, after locked dependency setup:

```sh
pnpm --filter @care-link/web build
VITE_SURFACE=help pnpm --filter @care-link/web build
pnpm exec vitest run apps/web/src
```

Configure origins using the approved environment before either build. Both commands write the same ignored `apps/web/dist` directory; preserve separately named artifacts during packaging. These commands build source and do not start or deploy a server.

The browser bootstraps CSRF at `/v1/auth/csrf` and uses `X-CSRF-Token` plus a stable `Idempotency-Key` on mutations. The identity callback may return a fixed HTML redirect; the user then checks sign-in again. `X-Ceremony-Id` on the current session response restores step-up state after that redirect, and `/v1/auth/step-up/proof` supplies the same-session proof reference for explicit confirmation. Proof and session data stay in memory. Cooling-off and second fresh MFA are enforced by the server. Re-enter the intended resource and purpose when starting a subsequent verification after a browser navigation; the UI does not save them in persistent browser storage.

A help acknowledgement and `accepted_unconnected` explicitly do not claim a staffed connection. Authority loss removes the displayed private result and disables private actions; the independently configured fallback link remains available. Before creating help, the browser obtains a durable operation key from `POST /help/v1/create-intent` with the same locale/jurisdiction payload. The help service returns the same key for that account across BFF sessions and page reloads until the linked request is cancelled. A changed payload is rejected rather than becoming a second request. After a return that resets the displayed language, restore the original request language (and original fictional jurisdiction, if applicable) before retrying; the help form currently sends a null jurisdiction. The EN/FR rejection message explains this recovery step without creating a replacement intent. The browser uses that key for `help_create`; losing either response can therefore be reconciled after a full OIDC navigation without a private browser cache. Other mutation retries retain their operation keys only in memory and still require current target/revision checks.

Automated component tests cover server roles, response validation, CSRF, identity loss, dropped-reply reconciliation, provider-origin validation, and step-up proof restoration. A real provider/browser, separate-account, keyboard/screenreader, and independent EN/FR review remain required qualification evidence.
