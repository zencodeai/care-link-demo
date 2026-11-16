# Shared-lab TLS renewal required for Option B

The 2026-11-13 live check found the existing provider, main, help and static HTTPS leaves expired on **2026-11-10 14:22:55 UTC**. The matching transport CA expired **2026-11-11 14:22:55 UTC**; the PostgreSQL certificate from the same PKI has the same expired leaf interval. Running containers alone do not provide a verified TLS connection.

Option B authorizes adding IMP-03 resources to shared services. This newly discovered maintenance also changes existing IMP-02 TLS files and briefly reconnects existing services. It therefore needs an explicit extension to the planned additive scope, preserving the workspace's IMP-02 protection constraint.

## Prepared candidate

New material is prepared outside source at `/private/tmp/care-link-imp03-003-shared/tls-renewal`, mode0700/files0600. Public hashes and exact validity windows are in [the candidate manifest](evidence/option-b-tls-renewal-candidate.json). Existing CA/leaf private keys and public-key identities are retained; CA validity is renewed for14days and existing service leaves for7days. Subjects, issuers, hostnames/SANs and extensions are preserved. A fresh manual.localhost certificate/key is supplied only for IMP-03. No existing file/service has been changed by preparation.

## Exact proposed scope

1. Back up the current public certificates and exact Kubernetes TLS Secret resource version privately. Update **only certificate entries** in `care-link-imp02-002/Secret/imp02-pki`: `ca.crt`, `postgres.crt`, `keycloak.crt`, `main.crt`, `help.crt`, `static.crt`. Leave its private-key entries unchanged. Preserve PostgreSQL data/PVCs, roles/passwords and all Keycloak realm/account data.
2. Replace the corresponding public certificates in `/private/tmp/care-link-imp02-002/secrets` with private backups retained. Update the identity application's mounted `ca.crt` and main proxy's `main.crt` under the exact `/var/lib/care-link/imp02-002/config/` paths in the named kind node. Do not touch signing/custody keys, SPIRE roots, issuer lifetimes, workload registrations or fence state.
3. Replace only `help.crt` in Docker volume `care-link-imp02-002-host-proxy-config` and `static.crt` in `care-link-imp02-002-static-config`. Do not alter the help spool, publication bytes, agent configuration/data or Workload API.
4. Wait for projected certificates to update, then reload PostgreSQL configuration without restarting its process. Restart only the existing Keycloak, identity and main deployments and the named host help proxy/static containers as needed to load refreshed certificates/CA trust. **Brief OIDC/main/help/static interruptions and browser reconnection or fresh sign-in may occur.** The host SPIRE agent and help application must remain running, preserving their memory-backed identity and spool.
5. Verify each refreshed HTTPS certificate against the renewed lab CA, verified PostgreSQL TLS, existing provider realm discovery, help/static availability and the affected bounded IMP-02 controls. Record exact changed file/resource hashes and observations. Existing G-02 snapshots remain historical; this maintenance is new evidence.

## Rollback and limits

Retain exact prior public files and Secret content privately; restore only those named certificate entries/files if application of the new candidate fails, reload/reconnect the same named processes, and preserve durable business/identity/fence state. The prior certificates are already expired, so restoring them does not restore verified serving. Do not reset databases, re-enrol SPIRE agents, change revocations, clear fences or use expired-certificate verification exceptions to claim success.

No macOS/system/browser trust store or hosts/DNS setting changes are proposed. Browser functional checks may use a recorded temporary-CA exception; those checks do not qualify browser CA trust. No stage acceptance, participant admission, model startup, next slice, commit or push follows from this maintenance.
