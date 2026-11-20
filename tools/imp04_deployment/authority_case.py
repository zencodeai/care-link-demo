"""One new, genuinely authenticated carer case; restriction never restores rights.

Only the root live operator invokes these fixed phases. Secrets stay in owner-only
files/stdin. Existing actors, realm settings, trust, ports and volumes are unchanged.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import secrets
import selectors
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from tools.imp02_application.tls import PinnedAddressTransport

from . import docker
from .config import (
    MAIN,
    PREFIX,
    PRIVATE,
    PROVIDER,
    REALM,
    Record,
    load,
    record,
    text,
    unique,
    write,
)

VERSION = "imp04.authority-case004.v1"
ACTION = "manual_identity_restrict"
CASE_NAME = "authority-case004.json"
PROOF_NAME = "authority-case004-proof.json"
BROWSER_NAME = "case004-browser.json"
_FIELDS = {
    "version",
    "target",
    "phase",
    "account_id",
    "operator_account_id",
    "username",
    "password",
    "totp_secret",
    "guard_floor_at",
    "pid_account_id",
    "provider_subject",
    "subject_id",
    "delegation_id",
    "operation_id",
    "nonce",
}
_PHASES = {
    "prepared",
    "provider_create_pending",
    "provider_created",
    "binding_pending",
    "ready",
    "delegation_pending",
    "delegation_admitted",
    "restriction_pending",
    "restricted",
}


def uuid(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Canonical issued UUID required")
    return value


def private_root() -> None:
    info = PRIVATE.lstat()
    if PRIVATE.is_symlink() or not PRIVATE.is_absolute() or not PRIVATE.is_dir():
        raise ValueError("Exact private target directory required")
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("Owner-only target directory required")


def original_browser() -> Record:
    private_root()
    value = load(PRIVATE / "browser.json")
    if value.get("mainOrigin") != MAIN or value.get("oidcOrigin") != PROVIDER:
        raise ValueError("Exact original target browser configuration required")
    if set(record(value["actors"])) != {
        "pid",
        "pid-other",
        "carer",
        "professional",
        "worker1",
        "worker2",
        "supervisor",
        "operator",
        "security",
    }:
        raise ValueError("Exact original nine issued actors required")
    return value


def case() -> Record:
    value = load(PRIVATE / CASE_NAME)
    browser = original_browser()
    actors = record(browser["actors"])
    original_ids = {text(record(item), "accountId") for item in actors.values()}
    if set(value) != _FIELDS or value["version"] != VERSION or value["target"] != PREFIX:
        raise ValueError("Exact isolated case receipt required")
    if value["phase"] not in _PHASES or uuid(value["account_id"]) in original_ids:
        raise ValueError("Only the separately created case principal is permitted")
    if uuid(value["operator_account_id"]) != text(record(actors["operator"]), "accountId"):
        raise ValueError("Original genuine operator binding required")
    if uuid(value["pid_account_id"]) != text(record(actors["pid"]), "accountId"):
        raise ValueError("Original genuine PID binding required")
    floor = text(value, "guard_floor_at")
    if not floor.endswith("Z") or datetime.fromisoformat(floor).tzinfo is None:
        raise ValueError("Recorded UTC new-subject guard floor required")
    for name in ("operation_id", "nonce"):
        uuid(value[name])
    for name in ("provider_subject", "subject_id", "delegation_id"):
        if value[name] is not None:
            uuid(value[name])
    if not re.fullmatch(r"imp04-s004-carer-[0-9a-f]{12}", text(value, "username")):
        raise ValueError("Exact new synthetic username required")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,96}", text(value, "password")) or not re.fullmatch(
        r"[A-Z2-7]{32}", text(value, "totp_secret")
    ):
        raise ValueError("Fresh private password/OTP material required")
    return value


def save(value: Record) -> None:
    current = PRIVATE / CASE_NAME
    load(current)
    temporary = PRIVATE / (".case004-" + uuid4().hex)
    write(temporary, json.dumps(value, separators=(",", ":")) + "\n")
    temporary.replace(current)


def public(value: Record, phase: str | None = None) -> Record:
    return {
        "target": PREFIX,
        "phase": phase or value["phase"],
        "account_id": value["account_id"],
        "provider_subject": value["provider_subject"],
        "subject_id": value["subject_id"],
        "delegation_id": value["delegation_id"],
        "operation_id": value["operation_id"],
        "nonce": value["nonce"],
        "guard_floor_at": value["guard_floor_at"],
        "pid_account_id": value["pid_account_id"],
    }


def prepare() -> Record:
    browser = original_browser()
    value: Record = {
        "version": VERSION,
        "target": PREFIX,
        "phase": "prepared",
        "account_id": str(uuid4()),
        "operator_account_id": text(record(record(browser["actors"])["operator"]), "accountId"),
        "username": "imp04-s004-carer-" + secrets.token_hex(6),
        "password": secrets.token_urlsafe(36),
        "totp_secret": base64.b32encode(secrets.token_bytes(20)).decode(),
        "guard_floor_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "pid_account_id": text(record(record(browser["actors"])["pid"]), "accountId"),
        "provider_subject": None,
        "subject_id": None,
        "delegation_id": None,
        "operation_id": str(uuid4()),
        "nonce": str(uuid4()),
    }
    write(PRIVATE / CASE_NAME, json.dumps(value, indent=2) + "\n")
    return public(case())


def provider_user(value: Record) -> Record:
    """The existing realm's actual password+OTP credential representation."""
    return {
        "username": value["username"],
        "enabled": True,
        "email": "imp04-case004@care-link.invalid",
        "emailVerified": False,
        "firstName": "Synthetic",
        "lastName": "Authority-loss qualification",
        "requiredActions": [],
        "credentials": [
            {"type": "password", "value": value["password"], "temporary": False},
            {
                "type": "otp",
                "userLabel": "imp04-case004-totp",
                "secretData": json.dumps({"value": value["totp_secret"]}),
                "credentialData": json.dumps(
                    {
                        "subType": "totp",
                        "digits": 6,
                        "period": 30,
                        "counter": 0,
                        "algorithm": "HmacSHA1",
                        "secretEncoding": "BASE32",
                    }
                ),
            },
        ],
    }


def issued_subject(location: str) -> str:
    parsed = urlsplit(location)
    expected = urlsplit(PROVIDER)
    if (parsed.scheme or parsed.netloc) and (
        parsed.scheme != expected.scheme or parsed.netloc != expected.netloc
    ):
        raise ValueError("Provider creation returned a different authority")
    prefix = "/admin/realms/" + REALM + "/users/"
    if parsed.query or parsed.fragment or not parsed.path.startswith(prefix):
        raise ValueError("Exact provider-issued user Location required")
    return uuid(parsed.path.removeprefix(prefix))


def provider_client() -> httpx.Client:
    return httpx.Client(
        base_url=PROVIDER,
        transport=PinnedAddressTransport(PROVIDER, "127.0.0.1", str(PRIVATE / "tls/ca.crt")),
        trust_env=False,
    )


def create_provider(value: Record) -> str:
    inputs = load(PRIVATE / "inputs.json")
    try:
        with provider_client() as client:
            token_reply = client.post(
                "/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": "imp04-owner-admin",
                    "password": text(inputs, "provider_admin_password"),
                },
                timeout=3,
                follow_redirects=False,
            )
            if token_reply.status_code != 200:
                raise ValueError("Own provider administration authentication unavailable")
            token = text(record(token_reply.json()), "access_token")
            headers = {"Authorization": "Bearer " + token}
            reply = client.post(
                "/admin/realms/" + REALM + "/users",
                json=provider_user(value),
                headers=headers,
                timeout=3,
                follow_redirects=False,
            )
            if reply.status_code != 201:
                raise ValueError("New case provider user was not created; existing user refused")
            subject = issued_subject(reply.headers.get("location", ""))
            actual = client.get(
                "/admin/realms/" + REALM + "/users/" + subject,
                headers=headers,
                timeout=3,
                follow_redirects=False,
            )
            if actual.status_code != 200:
                raise ValueError("Created provider user could not be independently read")
            row = record(actual.json())
            if (
                row.get("id") != subject
                or row.get("username") != value["username"]
                or row.get("enabled") is not True
            ):
                raise ValueError("Provider-issued case user binding differs")
            credential_reply = client.get(
                "/admin/realms/" + REALM + "/users/" + subject + "/credentials",
                headers=headers,
                timeout=3,
                follow_redirects=False,
            )
            if credential_reply.status_code != 200:
                raise ValueError("New case authenticator metadata unavailable")
            credentials: object = credential_reply.json()
            if not isinstance(credentials, list) or not {"password", "otp"}.issubset(
                {text(record(item), "type") for item in cast(list[object], credentials)}
            ):
                raise ValueError("Provider did not retain actual case password and OTP")
            return subject
    except (httpx.HTTPError, json.JSONDecodeError):
        raise RuntimeError(
            "Own provider case creation uncertain; inspect pending receipt"
        ) from None


SETUP_SCRIPT = r"""
import json,os,sys
from pathlib import Path
from psycopg.conninfo import conninfo_to_dict,make_conninfo
import psycopg
from care_link_identity import PostgresStore as IdentityStore,provision_account
from care_link_identity.crypto import digest
from tools.imp04_deployment.config import CONFIG,DATABASES,ISSUER,PG_HOST,PREFIX,load
from tools.imp03_shared.relay import ThreadedLoopbackBridge
v=json.loads(sys.stdin.read());root=Path(CONFIG)
if os.geteuid()!=0 or v['target']!=PREFIX:
 raise ValueError('Exact owned migration custodian required')
admin=load(root/'admin.json'); dsns={}
for role in ('identity','data'):
 cfg=load(root/role/'config.json',owned=False)
 if cfg['imp04_target']!=PREFIX:raise ValueError('Wrong target binding')
 settings=conninfo_to_dict(admin[role+'_admin_dsn'])
 expected={'host':PG_HOST,'hostaddr':'127.0.0.1','port':'5432','dbname':'postgres',
  'user':'postgres','sslmode':'verify-full','sslrootcert':CONFIG+'/'+role+'/shared-ca.crt'}
 if set(settings)!=set(expected)|{'password'} or any(settings[k]!=x for k,x in expected.items()):
  raise ValueError('Exact own admin endpoint required')
 dsns[role]=make_conninfo('',**{**settings,'dbname':DATABASES[role]})
bridge=ThreadedLoopbackBridge(Path(CONFIG).parent/'connectors/data-db/forward.sock',5432,server_uid=22042)
bridge.start()
try:
 with psycopg.connect(dsns['identity']) as con:
  if con.execute("SELECT 1 FROM identity.record WHERE kind='account' AND record_key=%s",
   (digest(ISSUER+'\0'+v['provider_subject']),)).fetchone():
   raise ValueError('Existing binding refused')
 with psycopg.connect(dsns['data']) as con:
  if con.execute('SELECT 1 FROM control.principal_guard WHERE principal_id=%s',
   (v['account_id'],)).fetchone():raise ValueError('Existing principal refused')
 provision_account(IdentityStore(dsns['identity']),ISSUER,v['provider_subject'],v['account_id'],['carer'])
 with psycopg.connect(dsns['data']) as con:
  control=con.execute("SELECT mode FROM control.guard WHERE key='demo' FOR UPDATE").fetchone()
  if control is None or control[0] not in ('normal','ai_disabled'):
   raise ValueError('Serving target required')
  con.execute('INSERT INTO control.principal_guard '
   '(principal_id,identity_revision,role_revision,role) VALUES(%s,1,1,%s)',
   (v['account_id'],'carer'))
 print(json.dumps({'identity_binding_created':True,'business_principal_created':True}))
finally:bridge.close()
"""


def operator(script: str, value: Record) -> Record:
    name = PREFIX + "-operator-seed"
    state = record(docker.inspect_container(name)["State"])
    if state.get("Status") != "exited":
        raise ValueError("Stopped owned operator seed required; another operation may be active")
    docker.start(name)
    try:
        return record(
            json.loads(
                docker.exec(name, ["python", "-c", script], stdin=json.dumps(value), root=True)
            )
        )
    finally:
        docker.stop(name)


def setup() -> Record:
    value = case()
    if value["phase"] != "prepared":
        raise ValueError("Fresh prepared case required; pending/existing setup is never adopted")
    value["phase"] = "provider_create_pending"
    save(value)
    value["provider_subject"] = create_provider(value)
    value["phase"] = "provider_created"
    save(value)
    value["phase"] = "binding_pending"
    save(value)
    result = operator(SETUP_SCRIPT, public(value))
    if result != {"identity_binding_created": True, "business_principal_created": True}:
        raise ValueError("Case binding result differs; inspect without regrant")
    value["phase"] = "ready"
    save(value)
    browser = copy.deepcopy(original_browser())
    actors = record(browser["actors"])
    actors["carer"] = {
        "accountId": value["account_id"],
        "role": "carer",
        "username": value["username"],
        "password": value["password"],
        "totpSecret": value["totp_secret"],
    }
    write(PRIVATE / BROWSER_NAME, json.dumps(browser, indent=2) + "\n")
    return public(value)


ADMIT_SCRIPT = r"""
import json,sys
from datetime import datetime
from pathlib import Path
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from tools.imp04_deployment.config import CONFIG,DATABASES,PG_HOST,PREFIX,load
from tools.imp04_deployment.provision import admit_delegation
from tools.imp03_shared.relay import ThreadedLoopbackBridge
v=json.loads(sys.stdin.read())
root=Path(CONFIG);cfg=load(root/'data/config.json',owned=False)
if cfg['imp04_target']!=PREFIX or v['target']!=PREFIX:raise ValueError('Wrong case target')
settings=conninfo_to_dict(load(root/'admin.json')['data_admin_dsn'])
expected={'host':PG_HOST,'hostaddr':'127.0.0.1','port':'5432','dbname':'postgres',
 'user':'postgres','sslmode':'verify-full','sslrootcert':CONFIG+'/data/shared-ca.crt'}
if set(settings)!=set(expected)|{'password'} or any(settings[k]!=x for k,x in expected.items()):
 raise ValueError('Exact own admin endpoint required')
b=ThreadedLoopbackBridge(Path(CONFIG).parent/'connectors/data-db/forward.sock',5432,server_uid=22042)
b.start()
try:
 with psycopg.connect(make_conninfo('',**{**settings,'dbname':DATABASES['data']})) as con:
  con.execute('SET TRANSACTION READ ONLY')
  persona=con.execute('SELECT created_at,account_id,kind,environment,population '
   'FROM core.persona WHERE id=%s',(v['subject_id'],)).fetchone()
  if (persona is None or persona[0]<datetime.fromisoformat(v['guard_floor_at'])
   or str(persona[1])!=v['pid_account_id'] or persona[2:]!=('pid','demo','synthetic')):
   raise ValueError('New native PID-created synthetic subject required')
 print(json.dumps(admit_delegation(Path(CONFIG),v['subject_id'],v['account_id'],
  v['delegation_id']),default=str))
finally:b.close()
"""


def admit(subject: str) -> Record:
    value = case()
    if value["phase"] != "ready":
        raise ValueError("New fully bound case required before delegation")
    value.update(subject_id=uuid(subject), delegation_id=str(uuid4()), phase="delegation_pending")
    save(value)
    result = operator(ADMIT_SCRIPT, public(value))
    if result.get("grantor_id") != value["account_id"] or result.get("subject_id") != subject:
        raise ValueError("Actual delegation binding differs")
    value["phase"] = "delegation_admitted"
    save(value)
    return {**public(value), "expires_at": result["expires_at"]}


def binding(value: Record) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "action": ACTION,
                "operation_id": value["operation_id"],
                "principal_id": value["account_id"],
                "expected_identity_revision": "1",
                "nonce": value["nonce"],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


PROOF_SCRIPT = r"""
import json,sys
from pathlib import Path
from tools.imp04_deployment.config import CONFIG,PREFIX,load
from tools.imp03_runtime.compose import Composition
v=json.loads(sys.stdin.read());cfg=load(Path(CONFIG)/'core/config.json')
if cfg['imp04_target']!=PREFIX:raise ValueError('Wrong core target')
c=Composition(cfg)
try:
 identity=c.identity(); actor=identity.authenticate(v['raw_session'])
 if actor.account_id!=v['operator_account_id'] or actor.role!='operator' or not actor.mfa:
  raise ValueError('Genuine native operator required')
 evidence=identity.evidence(actor,'manual_identity_restrict',v['binding_digest'],v['nonce'],None)
 print(json.dumps(evidence))
finally:
 for client in c.clients:client.close()
"""


def operator_cookie(path: Path) -> str:
    if not path.is_absolute() or PRIVATE not in path.parents or path.name != "operator.json":
        raise ValueError("Actual new-target native operator state required")
    value = load(path)
    cookies = value.get("cookies")
    if not isinstance(cookies, list):
        raise ValueError("Actual native operator cookie state required")
    selected: list[str] = []
    for item in cast(list[object], cookies):
        row = record(item)
        if row.get("name") == "__Host-care-link-session":
            if (
                row.get("domain") != "plans.localhost"
                or row.get("secure") is not True
                or row.get("path") != "/"
            ):
                raise ValueError("Exact main-origin secure host cookie required")
            selected.append(text(row, "value"))
    if len(selected) != 1:
        raise ValueError("One actual main-origin operator session required")
    return selected[0]


def proof(operator_state: Path) -> Record:
    value = case()
    if value["phase"] != "delegation_admitted" or (PRIVATE / PROOF_NAME).exists():
        raise ValueError(
            "New admitted case with no earlier proof required; expiry is never renewed"
        )
    request = {
        **public(value),
        "operator_account_id": value["operator_account_id"],
        "binding_digest": binding(value),
        "raw_session": operator_cookie(operator_state),
    }
    evidence = record(
        json.loads(
            docker.exec(
                PREFIX + "-core-app", ["python", "-c", PROOF_SCRIPT], stdin=json.dumps(request)
            )
        )
    )
    if (
        evidence.get("principal_id") != value["operator_account_id"]
        or evidence.get("action") != ACTION
        or evidence.get("request_digest") != binding(value)
        or evidence.get("nonce") != value["nonce"]
    ):
        raise ValueError("Actual operator proof binding differs")
    document = {
        "version": VERSION,
        **public(value),
        "operator_account_id": value["operator_account_id"],
        "expected_identity_revision": "1",
        "evidence": evidence,
    }
    write(PRIVATE / PROOF_NAME, json.dumps(document, separators=(",", ":")) + "\n")
    return {
        **public(value),
        "proof_expires_at": evidence["expires_at"],
        "expires_at": evidence["expires_at"],
    }


_RESTRICT_COMMON = r"""
import hashlib,json,sys
from datetime import UTC,datetime
from pathlib import Path
from care_link_core.manual_identity import HttpManualIdentity
from care_link_data import AESGCMContentCipher,ManualService,PostgresStore
import httpx
from tools.imp04_deployment.config import CONFIG,PREFIX,load
from tools.imp02_application.config import public_key
from tools.imp02_application.mesh import MeshTransport,explicit_credentials_only
from tools.imp03_runtime.remote import HttpChannels,HttpJournal,HttpPolicy
cfg=load(Path(CONFIG)/'data/config.json');clients=[]
if cfg['imp04_target']!=PREFIX:raise ValueError('Wrong data target')
def remote(role):
 target=cfg['outbound'][role]
 client=httpx.Client(transport=MeshTransport(Path(target['socket']),target['origin']),
  cookies=explicit_credentials_only(),trust_env=False)
 clients.append(client);return client,target['origin']
identity=HttpManualIdentity(*remote('identity'),public_key(cfg['identity_public_key']))
store=PostgresStore(cfg['store_dsn'])
service=ManualService(store,identity,HttpPolicy(*remote('pdp')),
 HttpJournal(*remote('journal'),public_key(cfg['journal_public_key'])),
 AESGCMContentCipher(Path(cfg['content_key']).read_bytes()),channel=HttpChannels(*remote('core')))
def execute(v,expected_case):
 for field in ('target','account_id','operator_account_id','operation_id','nonce'):
  if v[field]!=expected_case[field]:raise ValueError('Different case principal or command')
 if v['target']!=PREFIX or v['expected_identity_revision']!='1':
  raise ValueError('Wrong case revision')
 e=v['evidence']; expected=hashlib.sha256(json.dumps({'action':'manual_identity_restrict',
  'operation_id':v['operation_id'],'principal_id':v['account_id'],
  'expected_identity_revision':'1','nonce':v['nonce']},sort_keys=True,
  separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
 if (e['principal_id']!=v['operator_account_id'] or e['role']!='operator'
  or e['action']!='manual_identity_restrict' or e['request_digest']!=expected
  or e['nonce']!=v['nonce'] or e['resource_id'] is not None
  or datetime.fromisoformat(e['expires_at'])<=datetime.now(UTC)):
  raise ValueError('Exact fresh operator proof required')
 actor=identity.resolve(e)
 if actor.account_id!=v['operator_account_id'] or actor.role!='operator' or not actor.mfa:
  raise ValueError('Current genuine operator required')
 result=service.restrict_principal(actor,v['operation_id'],
  {'principal_id':v['account_id'],'expected_identity_revision':'1'})
 with store.transaction(actor,None,locked=False) as tx:
  principal=tx.get('principal',v['account_id'])
  if principal is None or principal['revoked'] is not True or principal['identity_revision']!=2:
   raise ValueError('Committed new-principal restriction not observed')
 return {'result':result,'principal_revoked':True}
"""

RESTRICT_SCRIPT = (
    _RESTRICT_COMMON
    + r"""
try:
 v=json.loads(sys.stdin.read());print(json.dumps(execute(v,json.loads(sys.argv[1]))))
finally:
 for client in clients:client.close()
"""
)

RESTRICT_SERVER = (
    _RESTRICT_COMMON
    + r"""
try:
 expected=json.loads(sys.argv[1])
 print(json.dumps({'ready':True,'target':PREFIX,'account_id':expected['account_id']}),flush=True)
 v=json.loads(sys.stdin.readline(8193));print(json.dumps(execute(v,expected)),flush=True)
finally:
 for client in clients:client.close()
"""
)


def restriction_input() -> tuple[Record, Record]:
    value = case()
    if value["phase"] != "delegation_admitted":
        raise ValueError("Only the unmodified new admitted case can be restricted")
    document = load(PRIVATE / PROOF_NAME)
    for name, expected in {
        "version": VERSION,
        **public(value),
        "operator_account_id": value["operator_account_id"],
        "expected_identity_revision": "1",
    }.items():
        if document.get(name) != expected:
            raise ValueError("Private proof and exact new case differ")
    evidence = record(document["evidence"])
    if (
        evidence.get("request_digest") != binding(value)
        or evidence.get("nonce") != value["nonce"]
        or datetime.fromisoformat(text(evidence, "expires_at")) <= datetime.now(UTC)
    ):
        raise ValueError("Proof expired or changed; no renewal or authority reset permitted")
    value["phase"] = "restriction_pending"
    save(value)
    return value, document


def restriction_result(value: Record, result: Record) -> Record:
    command = record(result["result"])
    if (
        command.get("resource_id") != value["account_id"]
        or command.get("revision") != "2"
        or command.get("state") != "committed"
        or result.get("principal_revoked") is not True
    ):
        raise ValueError("Restriction outcome uncertain; inspect without restoring rights")
    value["phase"] = "restricted"
    save(value)
    return {
        **public(value),
        **command,
        "principal_revoked": True,
        "principal_id": value["account_id"],
        "revoked": True,
        "authority_loss": "journalled_business_principal_revocation",
    }


def restrict() -> Record:
    value, document = restriction_input()
    expected = {**public(value), "operator_account_id": value["operator_account_id"]}
    result = record(
        json.loads(
            docker.exec(
                PREFIX + "-data-app",
                ["python", "-c", RESTRICT_SCRIPT, json.dumps(expected)],
                stdin=json.dumps(document),
            )
        )
    )
    return restriction_result(value, result)


def line_from(stream: IO[str], timeout: float = 15) -> str:
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        if not selector.select(timeout):
            raise TimeoutError("Case control channel deadline exceeded")
    line = stream.readline(8193)
    if not line or len(line) > 8192:
        raise ValueError("Bounded case control response required")
    return line


def channel() -> None:
    """Warm one fixed Data operation before minting the immutable short proof."""
    value = case()
    if value["phase"] != "delegation_admitted":
        raise ValueError("New admitted case required for fixed restriction channel")
    owned = docker.inspect_container(PREFIX + "-data-app")
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("Docker unavailable")
    expected = {**public(value), "operator_account_id": value["operator_account_id"]}
    child = subprocess.Popen(  # noqa: S603 - fixed script and inspected immutable container ID
        [
            executable,
            "exec",
            "--interactive",
            str(owned["Id"]),
            "python",
            "-u",
            "-c",
            RESTRICT_SERVER,
            json.dumps(expected),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    if child.stdin is None or child.stdout is None:
        child.kill()
        child.wait()
        raise RuntimeError("Private fixed case pipes unavailable")
    try:
        ready = record(json.loads(line_from(child.stdout)))
        if ready != {"ready": True, "target": PREFIX, "account_id": value["account_id"]}:
            raise ValueError("Wrong fixed case channel readiness")
        print(json.dumps(ready), flush=True)
        command = record(json.loads(line_from(sys.stdin, 120), object_pairs_hook=unique))
        if command != {"action": "restrict"}:
            raise ValueError("Only the fixed case restriction action is permitted")
        current, document = restriction_input()
        if current["account_id"] != value["account_id"] or current["nonce"] != value["nonce"]:
            raise ValueError("Fixed case changed after channel readiness")
        child.stdin.write(json.dumps(document) + "\n")
        child.stdin.flush()
        result = restriction_result(current, record(json.loads(line_from(child.stdout))))
        print(json.dumps(result), flush=True)
    finally:
        child.stdin.close()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        child.stdout.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=["prepare", "setup", "admit", "proof", "restrict", "channel"]
    )
    parser.add_argument("--subject")
    parser.add_argument("--operator-state", type=Path)
    args = parser.parse_args()
    if args.phase == "channel":
        channel()
        return
    if args.phase == "prepare":
        result = prepare()
    elif args.phase == "setup":
        result = setup()
    elif args.phase == "admit":
        if not args.subject:
            parser.error("--subject is required")
        result = admit(args.subject)
    elif args.phase == "proof":
        if not args.operator_state:
            parser.error("--operator-state is required")
        result = proof(args.operator_state)
    else:
        result = restrict()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
