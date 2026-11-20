"""Persistent owner-only timing control, avoiding Docker startup in a subsecond race."""

from __future__ import annotations

import shutil
import subprocess
import sys

from . import docker
from .config import PREFIX

SCRIPT = r"""
import json,os,sys,time
from datetime import UTC,datetime,timedelta
from uuid import UUID
from tools.imp04_deployment.qualification import DIRECTORY,_read,_write
from tools.imp04_deployment.config import load
cfg=load(DIRECTORY.parent/'config.json')
if cfg['imp04_target']!='care-link-imp04-002' or os.geteuid()!=22013:
 raise ValueError('Wrong timing custodian')
receipt=load(DIRECTORY.parent/'process.json')
if receipt.get('qualification_enabled') is not True:raise ValueError('Adapter inactive')
info=DIRECTORY.lstat()
if DIRECTORY.is_symlink() or info.st_uid!=os.geteuid() or info.st_mode&0o077:
 raise ValueError('Wrong timing directory')
print(json.dumps({'ready':True,'target':'care-link-imp04-002'}),flush=True)
def atomic(path,value):
 temporary=path.with_name('.control-'+str(UUID(int=int.from_bytes(os.urandom(16),'big'))))
 try:
  _write(temporary,value)
  os.link(temporary,path,follow_symlinks=False)
 finally:temporary.unlink(missing_ok=True)
for line in sys.stdin:
 try:
  if len(line)>2048:raise ValueError('Bounded control required')
  command=json.loads(line)
  if set(command)!={'action','phase','operation','actor','nonce'}:
   raise ValueError('Exact timing command required')
  action,phase,operation,actor,nonce=(command[k] for k in
   ('action','phase','operation','actor','nonce'))
  if (action not in {'arm','wait','release','finished'}
   or phase not in {'before_policy','before_final_output'}
   or operation not in {'plan_read','consent_grant'}):
   raise ValueError('Wrong bounded command')
  if any(str(UUID(x))!=x for x in (actor,nonce)):raise ValueError('Canonical identity required')
  if action=='arm':
   atomic(DIRECTORY/'armed.json',{'version':'imp04.qualification.v1',
    'target':'care-link-imp04-002','phase':phase,'action':operation,
    'actor_id':actor,'nonce':nonce,
    'expires_at':(datetime.now(UTC)+timedelta(seconds=5)).isoformat()})
   result={'armed':True}
  else:
   path=DIRECTORY/(('finished-' if action=='finished' else 'ready-')+nonce+'.json')
   deadline=time.monotonic()+3
   while True:
    try:
     result=_read(path)
     break
    except (FileNotFoundError,json.JSONDecodeError):
     if time.monotonic()>=deadline:raise TimeoutError('Timing receipt unavailable')
     time.sleep(0.002)
   if (result['nonce'],result['phase'],result['action'],result['actor_id'])!=(
    nonce,phase,operation,actor):raise ValueError('Timing receipt differs')
   if action=='release':
    atomic(DIRECTORY/('release-'+nonce+'.json'),{'nonce':nonce})
    result={'released':True,'nonce':nonce}
  print(json.dumps(result),flush=True)
 except Exception as error:
  print(json.dumps({'error':True,'category':type(error).__name__}),flush=True)
"""


def main() -> None:
    owned = docker.inspect_container(PREFIX + "-data-app")
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("Docker unavailable")
    # Inspect once before starting the immutable-ID, same-UID control process.
    # It accepts only timing commands; no generic exec/input or network API.
    result = subprocess.run(  # noqa: S603 - fixed command and inspected container ID
        [executable, "exec", "--interactive", str(owned["Id"]), "python", "-u", "-c", SCRIPT],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=120,
    )
    if result.returncode:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
