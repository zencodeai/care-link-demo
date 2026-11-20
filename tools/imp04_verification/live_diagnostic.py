"""Measure genuine actor requests through own core dependencies without content output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast
from uuid import UUID

from tools.imp04_deployment import docker
from tools.imp04_deployment.config import PREFIX, PRIVATE, load, record

PROBE = r"""
import json,re,sys,time
from pathlib import Path
from uuid import uuid4
from care_link_domain import ManualError
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_core.planning_http import HttpPlanningGateway
from tools.imp03_runtime.compose import Composition
from tools.imp03_runtime.remote import HttpPolicy
from tools.imp02_application.config import private_key
from tools.imp04_deployment.config import CONFIG,PREFIX,load

inputs=json.loads(sys.stdin.read())
cfg=load(Path(CONFIG)/'core/config.json')
if cfg['imp04_target']!=PREFIX:raise ValueError('Wrong diagnostic target')
c=Composition(cfg);identity=c.identity();client,origin=c.remote('data');pdp,po=c.remote('pdp')
observed=[]
def before(request):request.extensions['diagnostic_start']=time.monotonic()
def after(reply):
 reply.read();key=code=state=None
 if reply.status_code>=400:
  try:
   error=reply.json()
   candidate=error.get('message_key')
   if isinstance(candidate,str) and re.fullmatch(r'(manual|identity)\.[a-z_]{1,80}',candidate):
    key=candidate
   candidate=error.get('code')
   if isinstance(candidate,str) and re.fullmatch(r'[A-Z_]{1,80}',candidate):code=candidate
   candidate=error.get('state')
   if candidate in ('dependency_unavailable','denied'):state=candidate
  except (ValueError,AttributeError):pass
 observed.append({'host':reply.request.url.host,'path':reply.request.url.path,
  'status':reply.status_code,'bytes':len(reply.content),'code':code,'message_key':key,
  'state':state,'elapsed_ms':round(1000*(time.monotonic()-reply.request.extensions['diagnostic_start']))})
for dependency in c.clients:dependency.event_hooks={'request':[before],'response':[after]}
f=SignedEnvelopeFactory(client,origin,identity,HttpPolicy(pdp,po),private_key(cfg['core_signing_key']))
gateway=HttpPlanningGateway(client,origin,f)
results=[]
try:
 actor=identity.authenticate(inputs['session'])
 for operation in inputs['operations']:
  start=time.monotonic();offset=len(observed);result={'operation':operation}
  try:
   if operation=='plan_read':value=gateway.plan_read(actor,inputs['plan_id'])
   elif operation=='session_read':value=gateway.session_read(actor,inputs['session_id'])
   elif operation=='session_create':
    value=gateway.session_create(actor,str(uuid4()),{'tags':{'environment':'demo','population':'synthetic'},
     'participant_kind':'pid','jurisdiction':None,'locale':'en-CA','channel':'web',
     'persona_id':None,'fixture_id':None})
   else:value=gateway.directory_search(actor,str(uuid4()),{
    'jurisdiction':'CA-XX','need':'client_support',
    'locale':'fr-CA' if operation=='directory_fr' else 'en-CA','limit':50})
   result.update(status='passed',resource_id=value.get('id'),revision=value.get('revision'))
  except ManualError as error:
   result.update(status='failed',code=error.code,http_status=error.status)
  except Exception as error:
   result.update(status='diagnostic_failed',exception_class=type(error).__name__)
  result.update(elapsed_ms=round(1000*(time.monotonic()-start)),hops=observed[offset:])
  results.append(result)
 print(json.dumps({'target':PREFIX,'results':results,'actor_authentication':observed[:1],
  'content_returned':False,'credentials_returned':False}))
finally:
 for dependency in c.clients:dependency.close()
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--slot", choices=["pid", "carer", "worker2"], default="pid")
    parser.add_argument("--plan-id")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.state.parent != PRIVATE or args.state.is_symlink():
        raise ValueError("Exact new-target private session state directory required")
    if str(UUID(args.session_id)) != args.session_id:
        raise ValueError("Canonical existing synthetic session required")
    if args.plan_id and str(UUID(args.plan_id)) != args.plan_id:
        raise ValueError("Canonical actual synthetic plan required")
    state = load(args.state / ("sessions/" + args.slot + ".json"))
    cookies = state.get("cookies")
    if not isinstance(cookies, list):
        raise ValueError("Genuine browser cookie state required")
    issued = [
        record(cookie)["value"]
        for cookie in cast(list[object], cookies)
        if record(cookie).get("name") == "__Host-care-link-session"
    ]
    if len(issued) != 1:
        raise ValueError("One actual host session cookie required")
    operations = ["session_read", "directory_en", "directory_fr", "session_read"]
    if args.create:
        operations.append("session_create")
    if args.plan_id:
        operations = ["plan_read"]
    value = json.loads(
        docker.exec(
            PREFIX + "-core-app",
            ["python", "-c", PROBE],
            stdin=json.dumps(
                {
                    "session": issued[0],
                    "session_id": args.session_id,
                    "plan_id": args.plan_id,
                    "operations": operations,
                }
            ),
        )
    )
    with args.output.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
