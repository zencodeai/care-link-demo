"""Read-only bounded PostgreSQL wait sampling for the new runtime role only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.imp04_deployment import docker
from tools.imp04_deployment.config import PREFIX, record

PROBE = r"""
import json,time,sys,psycopg
from pathlib import Path
from psycopg.conninfo import make_conninfo
from tools.imp04_deployment.config import CONFIG,load
from tools.imp03_shared.relay import ThreadedLoopbackBridge
root=Path(CONFIG);admin=load(root/'admin.json')['data_admin_dsn']
database,login={'data':('imp04_runtime_002','imp04_data_runtime_002'),
 'identity':('imp04_identity_002','imp04_identity_runtime_002')}[sys.argv[2]]
bridge=ThreadedLoopbackBridge(root.parent/'connectors/data-db/forward.sock',5432,server_uid=22042)
bridge.start();samples=[];started=time.monotonic()
try:
 with psycopg.connect(make_conninfo(admin,dbname=database),autocommit=True) as c:
  c.execute('SET default_transaction_read_only=on')
  while time.monotonic()-started<int(sys.argv[1]):
   rows=c.execute("SELECT pid,state,wait_event_type,wait_event,pg_blocking_pids(pid),"
    "round(EXTRACT(epoch FROM clock_timestamp()-query_start)*1000),"
    "CASE WHEN query ILIKE '%%pg_advisory_xact_lock%%' THEN 'advisory_guard' "
    "WHEN query ILIKE 'SELECT record_key,payload::text%%' THEN 'identity_kind_scan' "
    "WHEN query ILIKE '%%identity.record%%' THEN 'identity_record' "
    "WHEN query ILIKE '%%plans.field%%' THEN 'plans.field' "
    "WHEN query ILIKE '%%control.guard%%' THEN 'control.guard' "
    "WHEN query ILIKE '%%audit.%%' THEN 'audit' "
    "WHEN query ILIKE '%%core.session%%' THEN 'core.session' "
    "WHEN query ILIKE '%%plans.plan%%' THEN 'plans.plan' "
    "WHEN query ILIKE '%%lifecycle.%%' THEN 'lifecycle' ELSE 'other' END, "
    "round(EXTRACT(epoch FROM clock_timestamp()-xact_start)*1000) "
    "FROM pg_stat_activity WHERE datname=%s "
    "AND usename=%s AND state<>'idle' ORDER BY pid",(database,login)).fetchall()
   if rows:samples.append({'elapsed_ms':round((time.monotonic()-started)*1000),'rows':rows})
   time.sleep(.025)
 print(json.dumps({'target':'care-link-imp04-002','runtime_role_only':True,'database':database,
  'columns':['pid','state','wait_event_type','wait_event','blocking_pids','query_age_ms',
   'table_category','transaction_age_ms'],
  'samples':samples,'sql_or_content_returned':False},default=str))
finally:bridge.close()
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, choices=range(1, 91), default=12)
    parser.add_argument("--database", choices=["data", "identity"], default="data")
    args = parser.parse_args()
    name = PREFIX + "-operator-seed"
    if record(docker.inspect_container(name)["State"])["Status"] != "exited":
        raise ValueError("Stopped owned operator required")
    docker.start(name)
    try:
        value = json.loads(
            docker.exec(name, ["python", "-c", PROBE, str(args.seconds), args.database], root=True)
        )
    finally:
        docker.stop(name)
    with args.output.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"wait_samples": len(value["samples"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
