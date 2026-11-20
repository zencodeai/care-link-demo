"""Control the receipt-bound new-target qualification timing adapter only."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from . import docker
from .config import PREFIX
from .qualification import DIRECTORY


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["arm", "wait", "release"])
    parser.add_argument(
        "--phase", choices=["before_policy", "before_final_output"], default="before_policy"
    )
    parser.add_argument("--operation", choices=["plan_read", "consent_grant"], default="plan_read")
    parser.add_argument("--actor")
    parser.add_argument("--nonce", required=True)
    args = parser.parse_args()
    if str(UUID(args.nonce)) != args.nonce:
        raise ValueError("Canonical barrier nonce required")
    if args.action == "arm":
        if not args.actor or str(UUID(args.actor)) != args.actor:
            raise ValueError("Canonical separately issued actor required")
        payload = {
            "version": "imp04.qualification.v1",
            "target": PREFIX,
            "phase": args.phase,
            "action": args.operation,
            "actor_id": args.actor,
            "nonce": args.nonce,
            "expires_at": (datetime.now(UTC) + timedelta(seconds=5)).isoformat(),
        }
        script = """
import json,os,sys
from pathlib import Path
p=Path(sys.argv[1]);p.mkdir(mode=0o700,exist_ok=True)
if p.is_symlink() or p.stat().st_uid!=os.geteuid() or p.stat().st_mode&0o077:
 raise ValueError('Private app-owned timing directory required')
f=p/'armed.json';fd=os.open(f,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as stream:stream.write(sys.argv[2])
print(json.dumps({'armed':True}))
"""
        output = docker.exec(
            PREFIX + "-data-app", ["python", "-c", script, str(DIRECTORY), json.dumps(payload)]
        )
    elif args.action == "wait":
        script = """
import json,sys,time
from pathlib import Path
p=Path(sys.argv[1]);deadline=time.monotonic()+0.7
while not p.is_file():
 if time.monotonic()>=deadline:raise TimeoutError('Timing adapter not entered')
 time.sleep(0.003)
print(p.read_text())
"""
        output = docker.exec(
            PREFIX + "-data-app",
            ["python", "-c", script, str(DIRECTORY / ("ready-" + args.nonce + ".json"))],
        )
    else:
        script = """
import os,sys,json
from pathlib import Path
p=Path(sys.argv[1]);nonce=sys.argv[2]
ready=p/('ready-'+nonce+'.json')
if json.loads(ready.read_text())['nonce']!=nonce:raise ValueError('Wrong ready binding')
fd=os.open(p/('release-'+nonce+'.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as stream:json.dump({'nonce':nonce},stream)
print(json.dumps({'released':True}))
"""
        output = docker.exec(
            PREFIX + "-data-app", ["python", "-c", script, str(DIRECTORY), args.nonce]
        )
    print(output.strip())


if __name__ == "__main__":
    main()
