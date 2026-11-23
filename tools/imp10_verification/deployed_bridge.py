"""Run the isolated IMP-10 host model bridge and its fixed provider transport."""

import argparse
import base64
import ipaddress
import json
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep
from typing import cast
from uuid import UUID

from care_link_inference_bridge.credentials import read_api_token
from care_link_inference_bridge.loaded import alias_files
from cryptography import x509

from tools.imp02_application.prepare import write
from tools.imp03_runtime.config import Record, record, text
from tools.imp06_runtime.release_custody_records import ReleaseObservation
from tools.imp06_runtime.routes import BRIDGE_ROUTES
from tools.imp06_runtime.serving_release import read_release_record
from tools.imp10_runtime.mesh import _render_role  # pyright: ignore[reportPrivateUsage]
from tools.imp10_verification.deployed_help import ROOT, command, docker, spire, wait_for
from tools.imp10_verification.deployed_release import (
    LEDGER,
    OBSERVATION,
    TRUST,
    load_qualification_bindings,
)

SCOPE = "care-link-imp10-008-model"
LABEL = "care-link.scope=" + SCOPE
NETWORK = "care-link-imp10-008-net"
NODE = "care-link-imp10-008-control-plane"
PROVIDER_NETWORK = SCOPE + "-provider-net"
ARTIFACT_VOLUME = SCOPE + "-artifact-pin"
AGENT_ID = "spiffe://care-link.demo/host/imp10-008-bridge"
BRIDGE_ID = "spiffe://care-link.demo/demo/host-inference-bridge"
INFERENCE_ID = "spiffe://care-link.demo/demo/inference"
ROLE = "host-inference-bridge"
APP = 21101
PROXY = 21102
AUTHORIZATION = 21103
FENCE = 21104
CONNECTOR = 21105
EGRESS = 21106
RESTRICT = 21107
RELEASE = 21108
BACKEND = "/sockets/backend/service.sock"
AUTH_SOCKET = "/sockets/authorization/service.sock"
FENCE_SOCKET = "/sockets/fence/service.sock"
PROVIDER_SOCKET = "/provider/service.sock"
AGENT_SOCKET = "/run/spire/sockets/agent.sock"
TRUST_BUNDLE = "/config/bundle.crt"
SETTINGS = "/config/config.json"

PORT = 8443
SVID_TTL = 300
DIRECTORIES = {
    "provider": (EGRESS, CONNECTOR, 0o710),
    "backend": (APP, PROXY, 0o710),
    "authorization": (AUTHORIZATION, PROXY, 0o710),
    "fence": (FENCE, PROXY, 0o710),
    "fence-state": (FENCE, FENCE, 0o700),
    "app-config": (APP, APP, 0o700),
    "harness": (APP, APP, 0o700),
    "release": (RELEASE, PROXY, 0o750),
    "proxy-config": (PROXY, PROXY, 0o700),
    "authorization-config": (AUTHORIZATION, AUTHORIZATION, 0o700),
    "fence-config": (FENCE, FENCE, 0o700),
    "agent-config": (0, 0, 0o700),
    "agent-state": (0, 0, 0o700),
    "workload-api": (0, 0, 0o755),
}
SEED = f"""
from pathlib import Path
import base64, json, os, sys
contents = json.load(sys.stdin)
for name, (uid, gid, mode) in {DIRECTORIES!r}.items():
    directory = Path('/volumes', name)
    os.chown(directory, uid, gid)
    directory.chmod(mode)
    for file, payload in contents.get(name, {{}}).items():
        if Path(file).name != file or file in ('.', '..'):
            raise ValueError('closed provisioned source names required')
        target = directory / file
        file_mode = 0o640 if name == 'release' else 0o600
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, file_mode)
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), uid, gid)
            stream.write(base64.b64decode(payload, validate=True))
            stream.flush()
            os.fsync(stream.fileno())
"""

PUBLISH_RELEASE = f"""
import base64, hashlib, json, os, sqlite3, sys
from pathlib import Path
root = Path('/release')
value = json.load(sys.stdin)
for name in ({OBSERVATION!r}, {TRUST!r}):
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != value[name]:
        raise ValueError('qualification observation or trust changed')
target = root / {LEDGER!r}
scratch = root / '.release-pending'
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
try:
    fd = os.open(scratch, flags, 0o640)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(base64.b64decode(value[{LEDGER!r}], validate=True))
        stream.flush()
        os.fsync(stream.fileno())
    connection = sqlite3.connect(scratch.as_uri() + '?mode=ro', uri=True)
    try:
        if connection.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise ValueError('qualification SQLite snapshot integrity failure')
    finally:
        connection.close()
    os.replace(scratch, target)
    dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)
finally:
    scratch.unlink(missing_ok=True)
"""

# Two fixed byte transports preserve both REST and authenticated SDK WebSocket
# framing, with no address/proxy/HTTP route selected by a caller.
RELAY = f"""
import ipaddress, os, select, socket, socketserver, threading, sys
from care_link_workload_trust.unix_server import peer_uid

purpose = sys.argv[1]
socket_path = {PROVIDER_SOCKET!r}
provider = ('host.docker.internal', 1234)
loopback = ('127.0.0.1', 1234)
capacity = threading.BoundedSemaphore(8)

def transfer(left, right):
    left.settimeout(5)
    right.settimeout(5)
    readers = [left, right]
    while readers:
        ready, _, _ = select.select(readers, [], [], 360)
        if not ready:
            return
        for source in ready:
            target = right if source is left else left
            data = source.recv(32768)
            if data:
                target.sendall(data)
            else:
                readers.remove(source)
                try:
                    target.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        if not capacity.acquire(blocking=False):
            return
        try:
            if purpose == 'egress':
                if peer_uid(self.request) != {CONNECTOR}:
                    return
                with socket.create_connection(destination, timeout=3) as upstream:
                    transfer(self.request, upstream)
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
                    upstream.settimeout(3)
                    upstream.connect(socket_path)
                    if peer_uid(upstream) != {EGRESS}:
                        return
                    transfer(self.request, upstream)
        except OSError:
            return
        finally:
            capacity.release()

if purpose == 'egress':
    endpoints = {{
        item[4][0] for item in socket.getaddrinfo(*provider, socket.AF_INET, socket.SOCK_STREAM)
    }}
    (destination_ip,) = endpoints
    address = ipaddress.IPv4Address(destination_ip)
    if not address.is_private or address.is_loopback or address.is_link_local:
        raise ValueError('private native model endpoint required')
    destination = (destination_ip, 1234)
    os.umask(0o117)
    server = socketserver.ThreadingUnixStreamServer(socket_path, Handler)
    os.chown(socket_path, -1, {CONNECTOR})
    os.chmod(socket_path, 0o660)
elif purpose == 'connector':
    server = socketserver.ThreadingTCPServer(loopback, Handler)
else:
    raise ValueError('exact private model relay role required')
server.daemon_threads = True
server.serve_forever(poll_interval=0.1)
"""

APP_HOLD = """
import os, sys
from time import monotonic, sleep
from pathlib import Path
from care_link_inference_bridge.bridge import LocalModelBridge
from care_link_inference_bridge.credentials import read_api_token
bridge = LocalModelBridge(api_token=read_api_token(Path('/config/model.token')))
deadline = monotonic() + 45
try:
    while True:
        try:
            bridge.require_authentication()
            break
        except OSError:
            if monotonic() > deadline:
                raise SystemExit('fixed active model transport unavailable') from None
            sleep(0.5)
finally:
    bridge.close()
if sys.argv[1] == 'preflight':
    sleep(200)
else:
    os.execv(sys.executable, [sys.executable, '-c',
        "from tools.imp10_verification.deployed_assistance import run;"
        "from tools.imp10_verification.bridge_observer import install;install();"
        "from pathlib import Path;run(Path('/config/config.json'))"])
"""

OBSERVATION_PREFIX = "IMP10_BRIDGE_SAMPLE "
FAILURE_PREFIX = "IMP10_BRIDGE_FAILURE "
OBSERVE_BRIDGE = f"""
import itertools, json
from datetime import UTC, datetime
from time import monotonic_ns
from care_link_domain import ManualError
from care_link_inference_bridge.artifacts import file_digest
from care_link_inference_bridge.bridge import LocalModelBridge
from care_link_inference_bridge.loaded import alias_files
from care_link_inference_bridge.tokenization import LMStudioTokenCounter, TokenizationDenied
from lmstudio import LMStudioError
from tools.imp06_runtime import role_process
from tools.imp06_runtime.releases import ReleaseBindings

def identity_guard(counter):
    current = counter.loaded_current
    facts = dict(zip(current.__code__.co_freevars,
                     (cell.cell_contents for cell in current.__closure__)))
    return {{
        'artifact_fingerprint_current': facts['artifact'].current(),
        'aliases_current': (
            alias_files(facts['index'], facts['artifact'].directory)==facts['aliases']
        ),
        'alias_digests_current': tuple(
            (path.name,file_digest(path)) for path in facts['aliases']
        )==facts['alias_digests'],
        'sdk_info_current': facts['handle'].get_info().to_dict()==facts['info'],
        'sdk_config_current': facts['handle'].get_load_config().to_dict()==facts['load_config'],
    }}

def guarded(operation, function, failures, reasons):
    def invoke(self, *args, **kwargs):
        try:
            return function(self, *args, **kwargs)
        except failures as error:
            candidate = error.code if isinstance(error, ManualError) else str(error)
            reason = candidate if candidate in reasons else None
            try:
                event = {{'operation': operation, 'reason': reason, 'class': type(error).__name__}}
                if reason == 'loaded_artifact_or_instance_changed':
                    try:
                        event['guard_components'] = identity_guard(self)
                    except (AttributeError, KeyError, ValueError, LMStudioError, OSError):
                        event['guard_components'] = None
                print({FAILURE_PREFIX!r}+json.dumps(event, sort_keys=True), flush=True)
            except OSError:
                pass
            raise
    return invoke

def install():
    LocalModelBridge.require_authentication = guarded(
        'catalog', LocalModelBridge.require_authentication, OSError,
        {{'local provider credential missing','local provider authentication not enforced',
          'local provider credential not accepted','local provider authentication unavailable'}},
    )
    LMStudioTokenCounter.count = guarded(
        'tokenizer', LMStudioTokenCounter.count, (TokenizationDenied, LMStudioError),
        {{'loaded_artifact_or_instance_changed','loaded_tokenizer_identity_changed',
          'invalid_tokenizer_result','rendered_template_limit'}},
    )
    ReleaseBindings.release = guarded(
        'release', ReleaseBindings.release, ManualError,
        {{'assistance.function_disabled','assistance.release_unverified'}},
    )
    original, observations = role_process.bridge_application, itertools.count(1)

    def factory(*args, **kwargs):
        product = original(*args, **kwargs)

        async def observe(scope, receive, send):
            if (
                scope['type'] != 'http'
                or scope['method'] != 'POST'
                or scope['path'] != '/internal/v1/inference/execute'
            ):
                await product(scope, receive, send)
                return

            start = monotonic_ns()
            start_utc = datetime.now(UTC).isoformat()
            index = next(observations)
            status = None
            payload = bytearray()
            within_limit = True

            async def measured_send(event):
                nonlocal status, within_limit
                if event['type'] == 'http.response.start':
                    status = event['status']
                if event['type'] == 'http.response.body' and status == 200 and within_limit:
                    data = event.get('body', b'')
                    if len(payload) + len(data) <= 65536:
                        payload.extend(data)
                    else:
                        payload.clear()
                        within_limit = False
                await send(event)

            try:
                await product(scope, receive, measured_send)
            finally:
                if status is not None and status != 403:
                    wall = round((monotonic_ns() - start) / 1e6, 3)
                    prompt, completion = None, None
                    if status == 200 and within_limit:
                        try:
                            usage = json.loads(payload)['usage']
                            a, b = usage['prompt_tokens'], usage['completion_tokens']
                            if type(a) is int and type(b) is int and a >= 0 and b >= 0:
                                prompt, completion = a, b
                        except (ValueError, TypeError, KeyError, RecursionError):
                            pass
                    sample = {{'sequence': index, 'status': status, 'started_at_utc': start_utc,
                               'bridge_ms': wall, 'prompt_tokens': prompt,
                               'completion_tokens': completion}}
                    try:
                        print({OBSERVATION_PREFIX!r}+json.dumps(sample, sort_keys=True), flush=True)
                    except OSError:
                        pass
        return observe

    role_process.bridge_application = factory
"""

AUTH_PROBE = """
from pathlib import Path
from care_link_inference_bridge.bridge import LocalModelBridge
from care_link_inference_bridge.credentials import read_api_token
bridge = LocalModelBridge(api_token=read_api_token(Path('/config/model.token')))
try:
    bridge.require_authentication()
    print('authenticated_catalog')
finally:
    bridge.close()
"""

MODEL_PROBE = """
import hashlib, json
from pathlib import Path
from time import monotonic
from care_link_inference_bridge.credentials import read_api_token
from care_link_inference_bridge.loaded import bind_loaded_model
from tools.imp06_runtime.release_custody_records import ReleaseObservation
path = Path('/config/observation.json')
pins = path.read_bytes()
expected = ReleaseObservation.model_validate_json(pins).model
started = monotonic()
binding = bind_loaded_model(
    Path('/model'), Path('/config/model-index.json'),
    api_token=read_api_token(Path('/config/model.token')),
)
try:
    current = binding.counter.loaded_current()
    fields = {
        key: value for key, value in expected.model_dump().items()
        if key in {'artifact_digest', 'tokenizer_digest', 'template_digest', 'model_window'}
    }
    if any(current.get(key) != value for key, value in fields.items()):
        raise ValueError('exact loaded qualification model pins required')
    result = {
        **fields,
        'role_observation_sha256': hashlib.sha256(pins).hexdigest(),
        'model_identifier': current['model_identifier'],
        'instance_sha256': hashlib.sha256(
            json.dumps(binding.model_info['instanceReference'], sort_keys=True).encode()
        ).hexdigest(),
        'exact_binding_elapsed_ms': round((monotonic() - started) * 1000, 3),
    }
    print(json.dumps(result, sort_keys=True))
finally:
    binding.close()
"""

STAGE_ARTIFACT = """
import json, os, shutil, sys
from pathlib import Path
from care_link_inference_bridge.artifacts import pin_artifact
source, destination = Path('/source'), Path('/artifact')
allow = {'.json','.jinja','.model','.safetensors','.txt','.tiktoken'}
files = [
    item for item in source.iterdir()
    if not item.name.startswith('.') and item.suffix in allow
]
if any(item.is_symlink() or not item.is_file() for item in files):
    raise ValueError('ordinary source artifact files required')
total = sum(item.stat().st_size for item in files)
space = os.statvfs(destination)
free = space.f_bavail * space.f_frsize
if total <= 0 or free < total + (1 << 30):
    raise ValueError('insufficient isolated artifact storage')
for item in files:
    output = destination / item.name
    with item.open('rb') as reader, output.open('xb') as writer:
        shutil.copyfileobj(reader, writer, length=4 * 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    output.chmod(0o444)
pins = pin_artifact(destination)
if pins.artifact_digest != sys.argv[1] or pins.tokenizer_digest != sys.argv[2]:
    raise ValueError('isolated copy differs from the exact candidate artifact')
print(json.dumps({'artifact_digest':pins.artifact_digest,'tokenizer_digest':pins.tokenizer_digest,
                  'bytes':total,'free_before_bytes':free,'files':len(pins.files)}))
"""

WRONG_UID_PROBE = f"""
import socket
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.settimeout(3)
    client.connect({PROVIDER_SOCKET!r})
    try:
        client.sendall(b'GET /api/v1/models HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\n\\r\\n')
        result = client.recv(80)
    except (BrokenPipeError, ConnectionResetError):
        result = b''
    if result:
        raise SystemExit('unexpected relay response for foreign UID')
    print('kernel_uid_denied')
"""


@dataclass(frozen=True)
class ModelInputs:
    directory: Path
    index: Path
    token: Path
    use_owned_volume: bool = False


@dataclass(frozen=True)
class BridgeRelease:
    shared: Path
    observation: Path
    boot_id: str


def _namespace() -> tuple[str, str]:
    network = record(json.loads(docker("network", "inspect", "--format", "{{json .}}", NETWORK)))
    if record(network["Labels"]).get("care-link.scope") != "imp10-008":
        raise ValueError("unexpected bridge lease owner")
    if docker("inspect", "--format", '{{index .Config.Labels "io.x-k8s.kind.cluster"}}', NODE) != (
        "care-link-imp10-008"
    ):
        raise ValueError("unexpected Kind lease owner")
    members = [record(value) for value in record(network["Containers"]).values()]
    (node,) = (item for item in members if text(item, "Name") == NODE)
    ranges = [
        text(record(item), "Subnet")
        for item in cast(list[object], record(network["IPAM"])["Config"])
    ]
    (subnet,) = (ipaddress.IPv4Network(value) for value in ranges if ":" not in value)
    host = str(subnet[-18])
    used = {text(item, "IPv4Address").split("/", 1)[0] for item in members}
    if not subnet.is_private or host in used:
        raise ValueError("dedicated model proxy address unavailable")
    return text(node, "IPv4Address").split("/", 1)[0], host


def _mount(name: str, path: str, *, readonly: bool = False) -> tuple[str, str]:
    flags = ",readonly" if readonly else ""
    return "--mount", f"type=volume,source={SCOPE}-{name},target={path}{flags}"


def _bind(source: Path, destination: str) -> tuple[str, str]:
    if not source.is_absolute() or "," in str(source):
        raise ValueError("absolute well-formed binding source required")
    return "--mount", f"type=bind,source={source},target={destination},readonly"


def _artifact_mount(model: ModelInputs) -> tuple[str, str]:
    if not model.use_owned_volume:
        return _bind(model.directory, "/model")
    if (
        docker(
            "volume", "inspect", "--format", '{{index .Labels "care-link.scope"}}', ARTIFACT_VOLUME
        )
        != SCOPE
    ):
        raise ValueError("isolated artifact volume is outside this lease")
    return "--mount", f"type=volume,source={ARTIFACT_VOLUME},target=/model,readonly"


def remove_model_copy() -> None:
    if (
        docker(
            "volume", "inspect", "--format", '{{index .Labels "care-link.scope"}}', ARTIFACT_VOLUME
        )
        != SCOPE
    ):
        raise ValueError("refusing to remove an unowned artifact")
    docker("volume", "rm", ARTIFACT_VOLUME)


def stage_model_copy(image: str, model: ModelInputs, observation: Path) -> Record:
    """Stream the already installed exact model bytes into a private Linux volume."""
    exact = _prepared_observation(image, observation)
    if ARTIFACT_VOLUME in docker("volume", "ls", "--format", "{{.Name}}").splitlines():
        raise ValueError("fresh isolated artifact volume required")
    docker("volume", "create", "--label", LABEL, ARTIFACT_VOLUME)
    try:
        output = command(
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--name",
            SCOPE + "-artifact-seed",
            "--label",
            LABEL,
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=0:0",
            *_bind(model.directory, "/source"),
            "--mount",
            f"type=volume,source={ARTIFACT_VOLUME},target=/artifact",
            image,
            "python",
            "-c",
            STAGE_ARTIFACT,
            exact.model.artifact_digest,
            exact.model.tokenizer_digest,
            timeout=240,
        )
        return record(json.loads(output))
    except BaseException:
        remove_model_copy()
        raise


@contextmanager
def _container(
    name: str, image: str, options: tuple[str, ...], args: tuple[str, ...]
) -> Iterator[str]:
    identifier = docker(
        "run",
        "--detach",
        "--pull=never",
        "--name",
        SCOPE + "-" + name,
        "--label",
        LABEL,
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=80",
        "--memory=220m",
        *options,
        image,
        *args,
    )
    try:
        yield identifier
    finally:
        owner = docker(
            "inspect", "--format", '{{index .Config.Labels "care-link.scope"}}', identifier
        )
        if owner != SCOPE:
            raise ValueError("refusing to remove an unowned model bridge container")
        docker("rm", "--force", identifier)


@contextmanager
def _resources() -> Iterator[None]:
    existing = docker("volume", "ls", "--format", "{{.Name}}").splitlines()
    if any(SCOPE + "-" + name in existing for name in DIRECTORIES):
        raise ValueError("fresh model bridge volumes required")
    provider = docker("network", "create", "--driver", "bridge", "--label", LABEL, PROVIDER_NETWORK)
    volumes: list[str] = []
    try:
        for name in DIRECTORIES:
            volumes.append(docker("volume", "create", "--label", LABEL, SCOPE + "-" + name))
        yield
    finally:
        for name in reversed(volumes):
            if (
                docker("volume", "inspect", "--format", '{{index .Labels "care-link.scope"}}', name)
                != SCOPE
            ):
                raise ValueError("refusing to remove an unowned model bridge volume")
            docker("volume", "rm", name)
        if (
            docker(
                "network", "inspect", "--format", '{{index .Labels "care-link.scope"}}', provider
            )
            != SCOPE
        ):
            raise ValueError("refusing to remove an unowned model bridge network")
        docker("network", "rm", provider)


def _seed(image: str, files: Mapping[str, Mapping[str, bytes]]) -> None:
    mounts = tuple(option for name in DIRECTORIES for option in _mount(name, "/volumes/" + name))
    values = {
        volume: {file: base64.b64encode(payload).decode() for file, payload in contents.items()}
        for volume, contents in files.items()
    }
    with _container(
        "seed",
        image,
        (
            "--network=none",
            "--user=0:0",
            "--cap-add=CHOWN",
            "--cap-add=FOWNER",
            "--cap-add=DAC_OVERRIDE",
            *mounts,
        ),
        ("python", "-c", "from time import sleep; sleep(60)"),
    ) as container:
        docker("exec", "-i", container, "python", "-c", SEED, stdin=json.dumps(values))


def _boot_material(model: ModelInputs) -> dict[str, bytes]:
    aliases = alias_files(model.index, model.directory.resolve(strict=True))
    manifest = {
        "models": [
            {
                "indexedModelIdentifier": "qwen/qwen3.8-27b",
                "concreteModelDirAbsolutePath": "/model",
                "containingDirAbsolutePath": "/config",
            }
        ],
    }
    return {
        "model.token": read_api_token(model.token).encode(),
        "model-index.json": json.dumps(manifest, separators=(",", ":")).encode(),
        **{path.name: path.read_bytes() for path in aliases},
    }


def _entry(kubeconfig: Path) -> list[Record]:
    entries = record(
        json.loads(spire(kubeconfig, "entry", "show", "-spiffeID", BRIDGE_ID, "-output", "json"))
    )["entries"]
    return [record(value) for value in cast(list[object], entries)]


@contextmanager
def _spire_sources(kubeconfig: Path, node: str) -> Iterator[tuple[dict[str, bytes], bytes]]:
    if _entry(kubeconfig):
        raise ValueError("an existing model bridge SPIRE registration is outside this run")
    spire(
        kubeconfig,
        "entry",
        "create",
        "-parentID",
        AGENT_ID,
        "-spiffeID",
        BRIDGE_ID,
        "-x509SVIDTTL",
        str(SVID_TTL),
        "-selector",
        f"unix:uid:{PROXY}",
    )
    (entry,) = _entry(kubeconfig)
    identifier = str(UUID(text(entry, "id")))
    try:
        if entry["parent_id"] != {
            "trust_domain": "care-link.demo",
            "path": "/host/imp10-008-bridge",
        } or (entry["selectors"] != [{"type": "unix", "value": f"uid:{PROXY}"}]):
            raise ValueError("exact model bridge Unix attestation required")
        response = record(
            json.loads(
                spire(
                    kubeconfig,
                    "token",
                    "generate",
                    "-spiffeID",
                    AGENT_ID,
                    "-ttl",
                    "600",
                    "-output",
                    "json",
                )
            )
        )
        bundle = spire(kubeconfig, "bundle", "show", "-format", "pem").encode()
        if not x509.load_pem_x509_certificates(bundle):
            raise ValueError("current SPIRE bundle required")
        config = f"""
agent {{
  trust_domain = "care-link.demo"
  data_dir = "/run/spire/data"
  server_address = "{node}"
  server_port = "30881"
  socket_path = "{AGENT_SOCKET}"
  trust_bundle_path = "{TRUST_BUNDLE}"
  join_token_file = "/config/join.token"
  log_level = "WARN"
}}
plugins {{
  NodeAttestor "join_token" {{ plugin_data {{ }} }}
  KeyManager "disk" {{ plugin_data {{ directory = "/run/spire/data/keys" }} }}
  WorkloadAttestor "unix" {{ plugin_data {{ }} }}
}}
"""
        yield (
            {
                "agent.conf": config.encode(),
                "bundle.crt": bundle,
                "join.token": text(response, "value").encode(),
            },
            bundle,
        )
    finally:
        spire(kubeconfig, "entry", "delete", "-entryID", identifier)


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _public_snapshot(shared: Path) -> dict[str, bytes]:
    source = shared / LEDGER
    with (
        closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)) as live,
        closing(sqlite3.connect(":memory:")) as snapshot,
    ):
        live.backup(snapshot)
        data = snapshot.serialize()
    return {
        LEDGER: data,
        OBSERVATION: (shared / OBSERVATION).read_bytes(),
        TRUST: (shared / TRUST).read_bytes(),
    }


def refresh_release(image: str, shared: Path) -> str:
    """Publish only a consistent reader snapshot after the operator changes ACK state."""
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None:
        raise ValueError("immutable bridge publisher image required")
    owner = docker(
        "volume", "inspect", "--format", '{{index .Labels "care-link.scope"}}', SCOPE + "-release"
    )
    if owner != SCOPE:
        raise ValueError("the current bridge release volume is outside this lease")
    source = _public_snapshot(shared)
    digest = sha256(source[LEDGER]).hexdigest()
    payload = {
        LEDGER: base64.b64encode(source[LEDGER]).decode(),
        OBSERVATION: sha256(source[OBSERVATION]).hexdigest(),
        TRUST: sha256(source[TRUST]).hexdigest(),
    }
    docker(
        "run",
        "--rm",
        "--interactive",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--name",
        SCOPE + "-release-publisher",
        "--label",
        LABEL,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user",
        f"{RELEASE}:{PROXY}",
        *_mount("release", "/release"),
        image,
        "python",
        "-c",
        PUBLISH_RELEASE,
        stdin=json.dumps(payload),
    )
    return digest


def _owned_running(role: str) -> str:
    if role not in {"app", "connector"}:
        raise ValueError("expected a bridge application or connector control")
    name = SCOPE + "-" + role
    metadata = record(json.loads(docker("inspect", "--format", "{{json .}}", name)))
    if (
        record(record(metadata["Config"])["Labels"]).get("care-link.scope") != SCOPE
        or not record(metadata["State"])["Running"]
    ):
        raise ValueError("current owned bridge control unavailable")
    return text(metadata, "Id")


def bridge_observations() -> list[Record]:
    """Return only the qualification request timings and token counts from this boot."""
    current_app = _owned_running("app")
    output = docker("logs", current_app)
    return [
        record(json.loads(line.removeprefix(OBSERVATION_PREFIX)))
        for line in output.splitlines()
        if line.startswith(OBSERVATION_PREFIX)
    ]


def bridge_failures() -> list[Record]:
    """Read only the allowlisted model failure labels from the owned process."""
    output = docker("logs", _owned_running("app"))
    return [
        record(json.loads(line.removeprefix(FAILURE_PREFIX)))
        for line in output.splitlines()
        if line.startswith(FAILURE_PREFIX)
    ]


@contextmanager
def pause_connector() -> Iterator[None]:
    """Interrupt only the owned sidecar transport, preserving native model state."""
    connector = _owned_running("connector")
    docker("pause", connector)
    try:
        yield
    finally:
        if _owned_running("connector") != connector:
            raise ValueError("bridge connector identity changed during the test")
        docker("unpause", connector)


def _proxy(host: str, products: Record) -> dict[str, Record]:
    images, versions = record(products["images"]), record(products["selected_versions"])
    return _render_role(
        ROLE,
        {
            ROLE: {
                "outbound": {},
                "address": host,
                "port": PORT,
                "spire_socket": AGENT_SOCKET,
                "backend_socket": BACKEND,
                "authorization_socket": AUTH_SOCKET,
                "authorization_uid": AUTHORIZATION,
                "trust_bundle": TRUST_BUNDLE,
                "proxy_uid": PROXY,
                "fence_socket": FENCE_SOCKET,
                "fence_uid": FENCE,
            }
        },
        {ROLE: {"inference": BRIDGE_ROUTES}},
        {
            "envoy_image": text(images, "envoy"),
            "envoy_version": text(versions, "envoy"),
            "spire_image": text(images, "spire_agent"),
            "spire_version": text(versions, "spire"),
            "svid_ttl_seconds": SVID_TTL,
        },
    )


def _trust_run(role: str) -> tuple[str, ...]:
    return (
        "python",
        "-c",
        (
            "from pathlib import Path;from tools.imp03_runtime.config import load;"
            "from tools.imp03_runtime.trust import serve;"
            f"serve({role!r},load(Path({SETTINGS!r})))"
        ),
    )


@contextmanager
def _provider(
    stack: ExitStack, image: str, app_options: tuple[str, ...], *, preflight: bool
) -> Iterator[tuple[str, str]]:
    egress = stack.enter_context(
        _container(
            "egress",
            image,
            (
                "--network",
                PROVIDER_NETWORK,
                "--user",
                f"{EGRESS}:{CONNECTOR}",
                *_mount("provider", "/provider"),
            ),
            ("python", "-c", RELAY, "egress"),
        )
    )
    wait_for(
        lambda: docker("exec", egress, "test", "-S", PROVIDER_SOCKET), "Provider relay did not bind"
    )
    app = stack.enter_context(
        _container(
            "app",
            image,
            (
                "--network=none",
                "--user",
                f"{APP}:{PROXY}",
                *app_options,
                *_mount("app-config", "/config", readonly=True),
            ),
            ("python", "-c", APP_HOLD, "preflight" if preflight else "launch"),
        )
    )
    stack.enter_context(
        _container(
            "connector",
            image,
            (
                "--network=container:" + app,
                "--user",
                f"{CONNECTOR}:{CONNECTOR}",
                *_mount("provider", "/provider", readonly=True),
            ),
            ("python", "-c", RELAY, "connector"),
        )
    )
    status = wait_for(
        lambda: docker("exec", app, "python", "-c", AUTH_PROBE),
        "Fixed authenticated model transport unavailable",
    )
    denied = docker("exec", egress, "python", "-c", WRONG_UID_PROBE)
    network_mode = docker("inspect", "--format", "{{.HostConfig.NetworkMode}}", app)
    if status != "authenticated_catalog" or denied != "kernel_uid_denied" or network_mode != "none":
        raise ValueError("provider transport did not enforce positive and adverse controls")
    yield app, egress


def _prepared_observation(image: str, location: Path) -> ReleaseObservation:
    observed = read_release_record(ReleaseObservation, location)
    if observed.image_digest != image.removeprefix("sha256:"):
        raise ValueError("role observation does not bind the local candidate image")
    return observed


def transport_preflight(
    image: str, model: ModelInputs, *, observation: Path | None = None, boot_id: str | None = None
) -> Record:
    if observation is not None:
        _prepared_observation(image, observation)
        if boot_id is None or str(UUID(boot_id)) != boot_id:
            raise ValueError("canonical supervisor boot required for model readiness")
    with ExitStack() as stack:
        stack.enter_context(_resources())
        files = {"model.token": read_api_token(model.token).encode()}
        if observation is not None:
            files.update({"observation.json": observation.read_bytes(), **_boot_material(model)})
        _seed(image, {"app-config": files})
        options = _artifact_mount(model) if observation is not None else ()
        with _provider(stack, image, options, preflight=True) as (app, _egress):
            receipt: Record = {
                "state": "passed",
                "anonymous_catalog": "denied",
                "authenticated_catalog": 200,
                "foreign_kernel_uid": "denied",
                "app_network_mode": "none",
                "model_inference_invoked": False,
            }
            if observation is not None:
                readiness = record(
                    json.loads(
                        command("docker", "exec", app, "python", "-c", MODEL_PROBE, timeout=175)
                    )
                )
                receipt["model_readiness"] = {"boot_id": boot_id, **readiness}
            return receipt


@contextmanager
def launch_bridge(
    image: str,
    kubeconfig: Path,
    release: BridgeRelease,
    model: ModelInputs,
) -> Iterator[Record]:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None:
        raise ValueError("immutable role image required")
    if str(UUID(release.boot_id)) != release.boot_id:
        raise ValueError("canonical supervised boot required")
    observation = _prepared_observation(image, release.observation)
    owner_uid = release.shared.stat().st_uid
    load_qualification_bindings(
        release.shared,
        owner_uid=owner_uid,
        role=ROLE,
        boot_id=release.boot_id,
        expected_observation=observation,
    ).release("worker_summary")
    node, host = _namespace()
    products = record(json.loads((ROOT / "deploy/k8s/imp-02/products.json").read_text()))
    rendered = _proxy(host, products)
    envoy = _json(rendered[ROLE + "-envoy.json"])
    scripts = {
        "__init__.py": b"",
        "bridge_observer.py": OBSERVE_BRIDGE.encode(),
        **{
            name: (ROOT / "tools" / "imp10_verification" / name).read_bytes()
            for name in ("deployed_assistance.py", "deployed_release.py")
        },
    }
    with ExitStack() as stack:
        stack.enter_context(_resources())
        sources, bundle = stack.enter_context(_spire_sources(kubeconfig, node))
        snapshot = _public_snapshot(release.shared)
        app_cfg = {
            "session": "imp10-protected",
            "role": ROLE,
            "uid": APP,
            "release_owner": RELEASE,
            "shared_release": "/release",
            "role_observation": "/config/observation.json",
            "boot_id": release.boot_id,
            "proxy_uid": PROXY,
            "fence_uid": FENCE,
            "fence_socket": FENCE_SOCKET,
            "backend_socket": BACKEND,
            "artifact_directory": "/model",
            "model_index": "/config/model-index.json",
            "lmstudio_token_file": "/config/model.token",
        }
        fence_cfg = {
            "session": "imp03-002",
            "uid": FENCE,
            "socket": FENCE_SOCKET,
            "ledger_directory": "/state",
            "access_gid": PROXY,
            "read_uids": [APP, AUTHORIZATION],
            "restrict_uid": RESTRICT,
            "allowed": [INFERENCE_ID, BRIDGE_ID],
        }
        _seed(
            image,
            {
                "app-config": {
                    "config.json": _json(app_cfg),
                    "observation.json": release.observation.read_bytes(),
                    **_boot_material(model),
                },
                "harness": scripts,
                "release": snapshot,
                "proxy-config": {"envoy.json": envoy},
                "authorization-config": {
                    "config.json": _json(rendered[ROLE + "-authorization.json"]),
                    "bundle.crt": bundle,
                },
                "fence-config": {"config.json": _json(fence_cfg)},
                "agent-config": sources,
            },
        )
        stack.enter_context(
            _container(
                "fence",
                image,
                (
                    "--network=none",
                    "--user",
                    f"{FENCE}:{PROXY}",
                    *_mount("fence", "/sockets/fence"),
                    *_mount("fence-state", "/state"),
                    *_mount("fence-config", "/config", readonly=True),
                ),
                _trust_run("fence"),
            )
        )
        stack.enter_context(
            _container(
                "authorization",
                image,
                (
                    "--network=none",
                    "--user",
                    f"{AUTHORIZATION}:{PROXY}",
                    *_mount("authorization", "/sockets/authorization"),
                    *_mount("fence", "/sockets/fence", readonly=True),
                    *_mount("authorization-config", "/config", readonly=True),
                ),
                _trust_run("authorization"),
            )
        )
        app, _egress = stack.enter_context(
            _provider(
                stack,
                image,
                (
                    *_mount("release", "/release", readonly=True),
                    *_artifact_mount(model),
                    *_mount("backend", "/sockets/backend"),
                    *_mount("fence", "/sockets/fence", readonly=True),
                    *_mount("harness", "/app/tools/imp10_verification", readonly=True),
                ),
                preflight=False,
            )
        )
        wait_for(
            lambda: docker("exec", app, "test", "-S", BACKEND),
            "Current qualified host bridge application did not bind",
            seconds=160,
        )
        images = record(products["images"])
        agent = stack.enter_context(
            _container(
                "agent",
                text(images, "spire_agent"),
                (
                    "--network",
                    NETWORK,
                    "--user=0:0",
                    *_mount("agent-config", "/config", readonly=True),
                    *_mount("agent-state", "/run/spire/data"),
                    *_mount("workload-api", "/run/spire/sockets"),
                ),
                ("-config", "/config/agent.conf"),
            )
        )
        proxy = stack.enter_context(
            _container(
                "proxy",
                text(images, "envoy"),
                (
                    "--network",
                    NETWORK,
                    "--ip",
                    host,
                    "--user",
                    f"{PROXY}:{PROXY}",
                    "--pid",
                    "container:" + agent,
                    *_mount("backend", "/sockets/backend", readonly=True),
                    *_mount("authorization", "/sockets/authorization", readonly=True),
                    *_mount("proxy-config", "/config", readonly=True),
                    *_mount("workload-api", "/run/spire/sockets", readonly=True),
                ),
                (
                    "-c",
                    "/config/envoy.json",
                    "--disable-hot-restart",
                    "--concurrency",
                    "1",
                    "--log-level",
                    "warning",
                ),
            )
        )
        yield {
            "state": "started",
            "scope": SCOPE,
            "proxy_address": host,
            "proxy_port": PORT,
            "app": app,
            "agent": agent,
            "proxy": proxy,
            "image_id": image,
            "workload": BRIDGE_ID,
            "boot_id": release.boot_id,
            "envoy_config_sha256": sha256(envoy).hexdigest(),
            "backend_socket": BACKEND,
            "authorized_provider_transport": "loopback_to_fixed_uds",
            "observed_protected_calls": [],
            "qualification_harness_sha256": {
                name: sha256(data).hexdigest() for name, data in scripts.items()
            },
            "release_snapshot_sha256": sha256(snapshot[LEDGER]).hexdigest(),
            "artifact_transport": "owned_linux_read_only_copy"
            if model.use_owned_volume
            else "read_only_bind",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--model-directory", required=True, type=Path)
    parser.add_argument("--model-index", required=True, type=Path)
    parser.add_argument("--model-token", required=True, type=Path)
    parser.add_argument("--owned-model-copy", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--kubeconfig", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--boot-id")
    parser.add_argument("--stop-marker", type=Path)
    args = parser.parse_args()
    model = ModelInputs(
        args.model_directory, args.model_index, args.model_token, args.owned_model_copy
    )
    image = docker("image", "inspect", "--format", "{{.Id}}", args.image)
    if args.preflight:
        observation = args.observation
        receipt = transport_preflight(image, model, observation=observation, boot_id=args.boot_id)
        write(args.output, _json({"image_id": image, **receipt}))
        return
    if not all((args.kubeconfig, args.release, args.observation, args.boot_id, args.stop_marker)):
        parser.error("live qualification requires explicit release, boot and stop inputs")
    if args.stop_marker.exists() or args.output.exists():
        parser.error("fresh stop marker and output paths required")
    release = BridgeRelease(args.release, args.observation, args.boot_id)
    with launch_bridge(image, args.kubeconfig, release, model) as receipt:
        write(args.output, _json(receipt))
        deadline = monotonic() + 1200
        while not args.stop_marker.is_file():
            if monotonic() >= deadline:
                raise RuntimeError("model bridge qualification lease reached its shutdown bound")
            sleep(0.2)


if __name__ == "__main__":
    main()
