"""Read-only public runtime binding, accepted preservation and authority snapshot.

No operation changes a container, role, credential, database, journal or fence.
The journal probe uses only the data role's own authenticated outbound socket
and verifies the signed nonce-bound reply before emitting public metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from tools.imp04_deployment import docker
from tools.imp04_deployment.config import PREFIX, PRIVATE, load, proposal, record, text

REPOSITORY = Path(__file__).resolve().parents[2]
SESSION = (
    REPOSITORY / "doc/IMP/slices/IMP-04-plans-consent-directory/sessions/003-live-qualification"
)
BASELINE = SESSION / "evidence/preflight-inventory.json"
INSPECT_FORMAT = (
    "{{json .Name}} {{json .Id}} {{json .Image}} {{json .State.Status}} "
    "{{json .State.StartedAt}} {{json .Mounts}} {{json .NetworkSettings.Networks}}"
)
NETWORK_FORMAT = (
    "{{json .Name}} {{json .Id}} {{json .Labels}} {{json .Driver}} "
    "{{json .Internal}} {{json .IPAM.Config}} {{json .Options}}"
)
FIELDS = ("name", "id", "image", "status", "started_at", "mounts", "networks")
Record = dict[str, object]

AUTHORITY_PROBE = r"""
import base64, hashlib, json, os, re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from care_link_workload_trust import UnixFenceClient
from tools.imp02_application.mesh import MeshTransport, explicit_credentials_only
from tools.imp04_deployment.config import CONFIG, PREFIX, load, record, text

cfg = load(Path(CONFIG) / 'data/config.json')
if cfg.get('imp04_target') != PREFIX or cfg.get('role') != 'data' or cfg.get('uid') != os.geteuid():
    raise ValueError('Exact data-role custodian required')
remote = record(record(cfg['outbound'])['journal'])
origin = text(remote, 'origin')
nonce = str(uuid4())
with httpx.Client(transport=MeshTransport(Path(text(remote, 'socket')), origin),
                  cookies=explicit_credentials_only(), trust_env=False) as client:
    response = client.post(origin + '/internal/v1/journal/head',
                           json={'nonce': nonce, 'command': None},
                           timeout=2, follow_redirects=False)
if response.status_code != 200 or len(response.content) > 65536:
    raise ValueError('Current journal head unavailable')
if not response.headers.get('content-type', '').startswith('application/json'):
    raise ValueError('Exact journal JSON response required')
def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate journal response key')
        value[key] = item
    return value
value = json.loads(response.content, object_pairs_hook=unique)
if set(value) != {'state', 'nonce', 'signature'} or value['nonce'] != nonce:
    raise ValueError('Journal nonce binding differs')
key = serialization.load_pem_public_key(Path(text(cfg, 'journal_public_key')).read_bytes())
if not isinstance(key, Ed25519PublicKey):
    raise ValueError('Exact Ed25519 journal verification key required')
unsigned = {name: item for name, item in value.items() if name != 'signature'}
canonical = json.dumps(unsigned, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
signature = value['signature']
if not isinstance(signature, str):
    raise ValueError('Exact journal signature required')
key.verify(base64.b64decode(signature + '=' * (-len(signature) % 4),
                           altchars=b'-_', validate=True), canonical)
state = record(value['state'])
expected = {'journal_id', 'generation', 'tip', 'tip_digest', 'restriction_barrier',
            'serving_generation', 'observed_at'}
if set(state) != expected:
    raise ValueError('Exact current journal state fields required')
if str(UUID(state['journal_id'])) != state['journal_id']:
    raise ValueError('Canonical journal identity required')
for field in ('generation', 'tip', 'restriction_barrier', 'serving_generation'):
    counter = state[field]
    if (not isinstance(counter, str) or not re.fullmatch(r'0|[1-9][0-9]{0,18}', counter)
            or int(counter) > 9223372036854775807):
        raise ValueError('Canonical nonnegative decimal journal counters required')
if (not isinstance(state['tip_digest'], str)
        or not re.fullmatch('[0-9a-f]{64}', state['tip_digest'])):
    raise ValueError('Exact journal tip digest required')
observed = datetime.fromisoformat(state['observed_at'].replace('Z', '+00:00'))
if observed.tzinfo is None or abs(datetime.now(UTC) - observed) > timedelta(seconds=1):
    raise ValueError('Fresh journal head required')
fence = UnixFenceClient(Path(text(cfg, 'fence_socket')), int(cfg['fence_uid'])).current()
print(json.dumps({
    'target': PREFIX,
    'journal': {'state': state, 'signature_verified': True, 'nonce_bound': True,
                'public_key_sha256': hashlib.sha256(key.public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw)).hexdigest()},
    'fence': {'generation': fence.generation, 'head': fence.head,
              'allowed': sorted(fence.allowed), 'denied': sorted(fence.denied),
              'command_count': len(fence.commands), 'kernel_verified_custodian': True}
}))
"""


def run_readonly(argv: list[str]) -> str:
    """Only fixed metadata commands constructed by this module reach Docker."""
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("Docker unavailable for public read-only snapshot")
    result = subprocess.run(  # noqa: S603 - fixed read-only metadata argv
        [executable, *argv], capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode:
        # Never relay a daemon diagnostic which could include raw configuration.
        raise RuntimeError("Public read-only Docker metadata unavailable")
    return result.stdout


def decode_seven(line: str) -> list[object]:
    """Decode exact JSON values, including nested mount/network metadata."""
    decoder = json.JSONDecoder()
    values: list[object] = []
    tail = line
    while tail.strip():
        item: object
        item, consumed = decoder.raw_decode(tail.lstrip())
        values.append(item)
        tail = tail.lstrip()[consumed:]
    if len(values) != 7:
        raise ValueError("Exactly seven public metadata values required")
    return values


def accepted_baseline() -> tuple[list[str], dict[str, list[object]]]:
    snapshot = record(json.loads(BASELINE.read_text()))
    checks = cast(list[Record], snapshot["checks"])
    matches = [
        check
        for check in checks
        if cast(list[str], check.get("argv", []))[:4]
        == ["docker", "inspect", "--format", INSPECT_FORMAT]
    ]
    if len(matches) != 1 or matches[0].get("exit_code") != 0:
        raise ValueError("One successful exact accepted metadata baseline required")
    command = cast(list[str], matches[0]["argv"])
    names = command[4:]
    if len(names) != 64 or len(set(names)) != 64:
        raise ValueError("Exact 64-resource accepted baseline required")
    if any(not name.startswith(("care-link-imp03-003-", "care-link-imp02-002-")) for name in names):
        raise ValueError("Only known accepted baseline resources may be inspected")
    rows = [decode_seven(line) for line in text(matches[0], "stdout").splitlines() if line]
    by_name = {str(row[0]).removeprefix("/"): row for row in rows}
    if set(by_name) != set(names) or len(rows) != len(names):
        raise ValueError("Accepted metadata baseline does not match its exact names")
    return names, by_name


def accepted_preservation() -> Record:
    names, baseline = accepted_baseline()
    output = run_readonly(["inspect", "--format", INSPECT_FORMAT, *names])
    rows = [decode_seven(line) for line in output.splitlines() if line]
    observed = {str(row[0]).removeprefix("/"): row for row in rows}
    if len(rows) != 64 or set(observed) != set(names):
        raise ValueError("Current accepted snapshot does not match exact baseline names")
    differences: list[Record] = []
    for name in names:
        changed = [
            field
            for index, field in enumerate(FIELDS)
            if baseline[name][index] != observed[name][index]
        ]
        if changed:
            differences.append({"name": name, "changed_fields": changed})
    return {
        "status": "passed" if not differences else "failed",
        "accepted_resources": 64,
        "comparison": "Exact seven decoded public JSON values, including full mounts/networks",
        "baseline_sha256": hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
        "differences": differences,
        "observed": [dict(zip(FIELDS, observed[name], strict=True)) for name in names],
    }


def own_containers() -> list[Record]:
    specs = cast(list[Record], proposal()["containers"])
    if len(specs) != 31:
        raise ValueError("Exact accepted new container enumeration required")
    output: list[Record] = []
    for spec in specs:
        name = text(spec, "name")
        metadata = docker.inspect_container(name)
        state, config = record(metadata["State"]), record(metadata["Config"])
        environment = cast(list[str], config.get("Env", []))
        output.append(
            {
                "name": name,
                "id": text(metadata, "Id"),
                "image": text(metadata, "Image"),
                "status": text(state, "Status"),
                "started_at": text(state, "StartedAt"),
                "mounts": metadata["Mounts"],
                "networks": record(metadata["NetworkSettings"])["Networks"],
                "qualification_enabled": "CARE_LINK_IMP04_QUALIFICATION=plans-002" in environment,
            }
        )
    return output


def own_networks() -> list[Record]:
    networks = cast(list[Record], proposal()["networks"])
    names = [text(network, "name") for network in networks]
    if len(names) != 4 or any(not name.startswith(PREFIX + "-") for name in names):
        raise ValueError("Four exact new target networks required")
    receipts = load(PRIVATE / "docker-resources.json")
    lines = run_readonly(["network", "inspect", "--format", NETWORK_FORMAT, *names]).splitlines()
    if len(lines) != 4:
        raise ValueError("Four current public network metadata rows required")
    output: list[Record] = []
    seen: set[str] = set()
    for line in lines:
        values = decode_seven(line)
        name, identifier = str(values[0]), str(values[1])
        if name not in names or name in seen:
            raise ValueError("Unexpected new network identity")
        seen.add(name)
        labels, receipt = record(values[2]), record(receipts["network:" + name])
        if (
            receipt.get("identity") != identifier
            or receipt.get("nonce") != labels.get("care-link.creation")
            or labels.get("care-link.scope") != "imp04-002"
        ):
            raise ValueError("Current network differs from exact creation receipt")
        output.append(
            {
                "name": name,
                "id": identifier,
                "driver": values[3],
                "internal": values[4],
                "ipam": values[5],
                "options": values[6],
            }
        )
    return output


def authority() -> Record:
    value = record(json.loads(docker.exec(PREFIX + "-data-app", ["python", "-c", AUTHORITY_PROBE])))
    if value.get("target") != PREFIX:
        raise ValueError("Wrong public authority snapshot target")
    return value


def snapshot() -> Record:
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "target": PREFIX,
        "read_only": True,
        "contains_credentials": False,
        "new_containers": own_containers(),
        "new_networks": own_networks(),
        "accepted_preservation": accepted_preservation(),
        "current_authority": authority(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.is_symlink() or not args.output.parent.is_dir():
        raise ValueError("Existing nonsymlink output directory required")
    value = snapshot()
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(value, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    preserved = record(value["accepted_preservation"])["status"] == "passed"
    print(
        json.dumps(
            {
                "snapshot_written": True,
                "new_containers": 31,
                "new_networks": 4,
                "accepted_preserved": preserved,
                "signed_journal_and_current_fence": True,
            }
        )
    )
    if not preserved:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
