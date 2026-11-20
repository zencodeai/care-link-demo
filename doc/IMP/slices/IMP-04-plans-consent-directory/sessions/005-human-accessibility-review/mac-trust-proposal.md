# Native Chrome/VoiceOver review setup proposal

Status: prepared, not applied. Chrome currently shows “Your connection is not private” for the IMP-04 origin. No warning was bypassed and no credentials were entered.

Approve only these two exact server certificates for SSL in the current Mac user’s login keychain:

| Certificate hostname | SHA-256 of DER certificate |
|---|---|
| `plans.localhost` | `c1c1f33dfbf4607f55bd17b2d492516735d2e7b300fa5d7ace29dfeee7f1646e` |
| `id.plans.localhost` | `d102ee77ef6c1ad8fce878acb0c08d089efe5512e4fb1116c9a6d29e150d9940` |

Both are non-CA certificates with exactly one DNS name each. They expire **November 18, 2026 at 2:02 p.m. Toronto time**. Their bytes match the current live endpoints and neither exact certificate is already in the login keychain. Trust affects this Mac user’s SSL clients, including Chrome; it is not confined to the private review window. The certificate’s exact bytes, existing DNS name, non-CA constraints and expiry bound the change. No CA root is added.

Exact commands:

```sh
/usr/bin/security add-trusted-cert -r trustAsRoot -p ssl -k /Users/main/Library/Keychains/login.keychain-db /private/tmp/care-link-imp04-002/tls/manual.crt
/usr/bin/security add-trusted-cert -r trustAsRoot -p ssl -k /Users/main/Library/Keychains/login.keychain-db /private/tmp/care-link-imp04-002/tls/keycloak.crt
```

Native certificate, hostname and expiry validation stay enabled. The System keychain, existing trust entries, accepted IMP-03 profiles/runtime, DNS and application images stay unchanged. No `ignoreHTTPSErrors`, certificate-warning bypass, CA/private-key import or software installation is proposed.

[Chromium’s trust implementation](https://chromium.googlesource.com/chromium/src/+/main/net/cert/internal/trust_store_mac.cc) skips application- and hostname-constrained macOS trust records. This proposal therefore uses SSL-only trust for the two exact leaves; normal certificate DNS-name checking provides the hostname boundary. [Apple documents non-root certificate trust](https://developer.apple.com/documentation/security/sectrustsettingsresult/trustasroot).

After approval, verify native Mac trust, normal Chrome navigation to main and provider, wrong-hostname denial, and absence of non-SSL trust. If any check fails, stop without broadening trust. An OS authorization prompt, if shown, is for the user to complete; no Mac password is requested in chat.

After the human review, remove only these newly imported exact certificates and their user trust:

```sh
/usr/bin/security delete-certificate -t -Z c1c1f33dfbf4607f55bd17b2d492516735d2e7b300fa5d7ace29dfeee7f1646e /Users/main/Library/Keychains/login.keychain-db
/usr/bin/security delete-certificate -t -Z d102ee77ef6c1ad8fce878acb0c08d089efe5512e4fb1116c9a6d29e150d9940 /Users/main/Library/Keychains/login.keychain-db
```

The previous headless-only packet excluded Mac/global trust changes. This is a separate, concrete request for a narrowly bounded Mac user-trust change. Approval of this setup is not G-04 acceptance. See [machine-readable proposal](mac-trust-proposal.json) and [actual preflight](native-review-preflight.json).
