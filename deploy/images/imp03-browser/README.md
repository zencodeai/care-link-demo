# Isolated qualification browser

The Dockerfile pins the official Linux Playwright image by digest and adds NSS
certificate tooling, the existing locked playwright-core1.65.0 tree and public
CA certificates. Build context is staged privately; no repository, actor secrets,
private keys or tests are copied. Actual image/container binding is recorded in
session003 continuation evidence.

Chromium146+ uses `$HOME/.local/share/pki/nssdb`. Import only the two exact lab
roots in the dedicated browser-home volume. Start the remote server as UID1000
with read-only root, dropped capabilities and loopback-only publication29900;
keep its random path/endpoint in the owner-only private file. The loopback
network exposure tunnels bytes without terminating origin TLS. Node trusts only
the process-scoped `NODE_EXTRA_CA_CERTS` bundle. Chromium retains
`ignoreHTTPSErrors:false`; wrong-hostname rejection was verified. No Mac global
trust store or DNS edits are required. Existing context/endpoint files are not
restart/provision instructions; see the current session003 handoff.

Official references: [Playwright Docker](https://playwright.dev/docs/docker),
[official image](https://mcr.microsoft.com/product/playwright),
[Chromium NSS certificate management](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/cert_management.md),
[remote connection](https://playwright.dev/docs/api/class-browsertype#browser-type-connect)
and [Node process CA bundle](https://nodejs.org/api/cli.html#node_extra_ca_certsfile).
