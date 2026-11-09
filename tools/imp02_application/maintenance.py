"""Offline owner review CLI, using fresh PKCE/MFA and no general browser grant.

Execute only inside the assigned identity custody. The short-lived private state
file belongs to that kernel owner; callback URLs/PKCE binding never enter reports.
Ordinary BFF callback intentionally rejects this purpose before code redemption.
"""

import argparse
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlsplit

from care_link_identity import OwnerAccessReview

from .config import load
from .identity import IdentityApplication
from .prepare import write


def state_file(path: Path) -> dict[str, str]:
    metadata = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise ValueError("Own private maintenance file required")
    value: object = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Invalid maintenance state")
    result = cast(dict[str, object], value)
    if set(result) != {"binding", "intent_id", "authorization_url"}:
        raise ValueError("Invalid maintenance state")
    if not all(isinstance(v, str) for v in result.values()):
        raise ValueError("Invalid maintenance state values")
    return cast(dict[str, str], result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("begin", "complete", "approve", "decline"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--owner-account-id", required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    app = IdentityApplication(load(args.config))
    authority = OwnerAccessReview(app.services["main"], args.owner_account_id)
    if args.phase == "begin":
        if (
            args.state.parent.stat().st_uid != os.geteuid()
            or args.state.parent.stat().st_mode & 0o077
        ):
            raise ValueError("Own0700 temporary maintenance directory required")
        binding = secrets.token_urlsafe(32)
        result = authority.begin(binding)
        write(
            args.state,
            json.dumps(
                {
                    "binding": binding,
                    "intent_id": result["intent_id"],
                    "authorization_url": result["authorization_url"],
                }
            ).encode(),
        )
        # This short-lived authorization URL is intentionally written only to the
        # caller-selected private file. Opening it is an explicit operator step.
        print(
            json.dumps(
                {
                    "phase": "pending_fresh_mfa",
                    "private_state": str(args.state),
                    "ambient_grant": False,
                }
            )
        )
        return
    state = state_file(args.state)
    if args.phase == "complete":
        # Operator supplies the returned callback URL via stdin, never argv/logs.
        callback = sys.stdin.readline(8193).strip()
        parsed = urlsplit(callback)
        expected = urlsplit(app.services["main"].origin)
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        if (
            (parsed.scheme, parsed.netloc, parsed.path)
            != (expected.scheme, expected.netloc, "/v1/auth/callback")
            or len(callback) > 8192
            or parsed.fragment
            or not set(query) <= {"state", "code", "iss", "session_state"}
            or not {"state", "code"} <= set(query)
            or any(len(v) != 1 for v in query.values())
        ):
            raise ValueError("Exact maintenance callback required")
        proof = authority.complete(
            query["state"][0], query["code"][0], state["binding"], query.get("iss", [None])[0]
        )
        if proof.proof_id != state["intent_id"]:
            raise ValueError("Maintenance binding differs")
        print(
            json.dumps({"phase": "awaiting_explicit_owner_review_decision", "ambient_grant": False})
        )
        return
    approved = authority.confirm(
        state["intent_id"], state["binding"], approve=args.phase == "approve"
    )
    args.state.unlink()
    print(json.dumps({"own_access_review_renewed": approved, "ambient_grant": False}))


if __name__ == "__main__":
    main()
