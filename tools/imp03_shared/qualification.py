"""Run one live barrier on the already issued Option B runtime.

Private browser output is retained. Only hashes/counts and enumerated outcomes
leave the custodian. This never provisions, resets, or adopts runtime state.
"""

import argparse
import json
import os
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from tools.imp03_verification.live_barrier import acknowledge

from . import docker
from .deployment import create, name
from .infrastructure import private_write
from .model import CONFIG, PRIVATE, ROOT, Record, mount

EVIDENCE = Path(
    "doc/IMP/slices/IMP-03-protected-manual-service/sessions/003-live-qualification/evidence"
)
PHASES = ("identity-loss", "pdp-loss", "journal-loss", "audit-loss", "fenced")

# Runs only in the fresh, labelled, network-none provisioning supervisor.
# The read-only snapshot covers complete business rows without exporting them.
SNAPSHOT = (
    f"ROOT={CONFIG!r}\nSOCKET={ROOT + '/connectors/data-db/forward.sock'!r}\n"  # noqa: S608
    + """
import hashlib,json
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from tools.imp03_shared.relay import ThreadedLoopbackBridge
from tools.imp03_runtime.config import load
root=Path(ROOT)
settings=conninfo_to_dict(load(root/'admin.json')['data_admin_dsn'])
settings['dbname']='imp03_runtime_002'
receipt=load(root/'receipt.json')
with ThreadedLoopbackBridge(Path(SOCKET),5432,server_uid=22042):
 with psycopg.connect(make_conninfo(**settings),connect_timeout=2) as conn:
  conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  bound=conn.execute("SELECT journal_id FROM control.guard WHERE key='demo'").fetchone()
  assert str(bound[0])==receipt['journal_id']
  tables=conn.execute("SELECT schemaname,tablename FROM pg_tables WHERE "
   "schemaname IN ('core','workforce','access','lifecycle','control') ORDER BY 1,2").fetchall()
  result={}
  for schema,table in tables:
   query=sql.SQL('SELECT row_to_json(t)::text FROM {}.{} t')
   rows=conn.execute(query.format(sql.Identifier(schema),sql.Identifier(table))).fetchall()
   encoded=json.dumps(sorted(row[0] for row in rows),separators=(',',':')).encode()
   result[schema+'.'+table]={'count':len(rows),'sha256':hashlib.sha256(encoded).hexdigest()}
  effects=conn.execute("SELECT operation_name,count(*) FROM durable.operation "
   "WHERE state='committed' GROUP BY operation_name ORDER BY operation_name").fetchall()
  ssl=conn.execute('SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone()
  print(json.dumps({'business':result,'committed_operations':effects,'postgres_tls':ssl}))
"""
)


def snapshot() -> Record:
    return json.loads(docker.exec(name("operator-seed"), ["python", "-c", SNAPSHOT], root=True))


def fault(phase: str, *, pause: bool) -> None:
    action = "pause" if pause else "resume"
    if phase == "fenced":
        if not pause:
            raise ValueError("A workload restriction has no restore operation")
        create(
            "fence-restrict",
            ["python", "-c", "import time;time.sleep(120)"],
            [mount("fence", ROOT + "/fence", readonly=True)],
            uid=22001,
            groups=["22999"],
        )
        docker.start(name("fence-restrict"))
        try:
            script = (
                "import json;from care_link_workload_trust import UnixFenceClient;"
                "from pathlib import Path;"
                f"c=UnixFenceClient(Path('{ROOT}/fence/fence.sock'),22000);"
                "s=c.read();assert s.generation==0 and not s.denied;"
                f"r=c.restrict('spiffe://care-link.demo/demo/core','{uuid4()}',0);"
                "assert r.durable and r.generation==1;"
                "print(json.dumps({'generation':r.generation,'durable':r.durable}))"
            )
            receipt = docker.exec(name("fence-restrict"), ["python", "-c", script])
            private_write(EVIDENCE / "option-b-one-way-fence-receipt.json", receipt)
        finally:
            docker.stop(name("fence-restrict"))
            docker.remove_owned(name("fence-restrict"))
    elif phase == "audit-loss":
        script = (
            "from pathlib import Path;"
            "from tools.imp03_shared.relay import ThreadedLoopbackBridge;"
            "from tools.imp03_runtime.config import load;"
            "from tools.imp03_verification.audit_fault import apply;"
            f"b=ThreadedLoopbackBridge(Path('{ROOT}/connectors/data-db/forward.sock'),"
            "5432,server_uid=22042);b.start();"
            f"apply(Path('{CONFIG}'),load(Path('{CONFIG}/admin.json')),pause={pause!r});"
            "b.close()"
        )
        docker.exec(name("operator-seed"), ["python", "-c", script], root=True)
    else:
        role = phase.removesuffix("-loss")
        docker.exec(
            name(role + "-app"),
            [
                "python",
                "-m",
                "tools.imp03_runtime",
                "fault",
                "--root",
                CONFIG,
                "--role",
                role,
                "--action",
                action,
            ],
            root=False,
        )


def run(
    phase: str,
    attempt: int,
    private: Path = PRIVATE,
    *,
    observe: Callable[[], Record] | None = None,
    compare: Callable[[Record, Record], Record] | None = None,
    quiescence_seconds: float = 0,
) -> Record:
    if phase not in PHASES or not 1 <= attempt <= 999:
        raise ValueError("One named reversible barrier and fresh attempt required")
    if not 0 <= quiescence_seconds <= 2:
        raise ValueError("Bounded pre-fault request quiescence required")
    os.umask(0o077)
    output = private / f"live-{phase}-{attempt:03}"
    if output.exists():
        raise ValueError("Existing browser attempt refused")
    output.mkdir(mode=0o700)
    env = {
        **os.environ,
        "PLAYWRIGHT_BROWSERS_PATH": str(private / "browser-cache"),
        "CARE_LINK_IMP03_E2E_CONFIG": str(private / "browser.json"),
        "CARE_LINK_IMP03_E2E_OUTPUT": str(output),
        "CARE_LINK_IMP03_PHASE": phase,
    }
    result: Record = {"phase": phase, "attempt": attempt, "human_acceptance": False}
    applied = False
    confirmed = False
    started = time.monotonic()
    log = private / (output.name + ".log")
    try:
        with log.open("x") as stream:
            process = subprocess.Popen(  # noqa: S603 - fixed locked browser command
                [  # noqa: S607 - existing locked local package runner
                    "pnpm",
                    "exec",
                    "playwright",
                    "test",
                    "--config",
                    "tests/e2e/imp03/playwright.config.ts",
                ],
                env=env,
                start_new_session=True,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 100
                while not (output / "barrier-ready.json").exists():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Live browser did not reach barrier readiness")
                    time.sleep(0.2)
                observer = observe or snapshot
                if quiescence_seconds:
                    time.sleep(quiescence_seconds)
                    result["pre_fault_quiescence_seconds"] = quiescence_seconds
                before = observer()
                # Cleanup is armed before attempting the mutation, including
                # partially successful Docker/DB calls with a lost reply.
                applied = True
                fault(phase, pause=True)
                confirmed = True
                acknowledge(output, phase)
                code = process.wait(timeout=150)
                after = observer()
                comparison = (
                    compare(before, after)
                    if compare
                    else {"no_prohibited_observed_effect": before == after}
                )
                result.update(
                    exit_code=code,
                    before=before,
                    after=after,
                    effect_comparison=comparison,
                    forbidden_business_effect_absent=comparison["no_prohibited_observed_effect"],
                )
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
    finally:
        try:
            if applied and phase != "fenced":
                fault(phase, pause=False)
                result["exact_barrier_restored"] = True
            elif applied:
                result["one_way_restriction_retained"] = confirmed
                result["restriction_state_unknown"] = not confirmed
        finally:
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            result["private_output"] = str(output)
            private_write(
                EVIDENCE / ("option-b-" + output.name + ".json"), json.dumps(result, indent=2)
            )
    if result.get("exit_code") == 0:
        observations = json.loads((output / "observations.json").read_text())
        private_write(
            EVIDENCE / ("option-b-" + output.name + "-observations.json"),
            json.dumps(observations, indent=2),
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    result = run(args.phase, args.attempt)
    print(json.dumps({k: v for k, v in result.items() if k not in {"before", "after"}}))
    if result.get("exit_code") != 0 or result.get("forbidden_business_effect_absent") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
