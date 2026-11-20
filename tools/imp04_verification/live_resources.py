"""Public cgroup/process observations for the exact new policy and browser targets."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from tools.imp04_deployment import docker
from tools.imp04_deployment.config import PREFIX, record

PYTHON = r"""
import json
from pathlib import Path
root=Path('/sys/fs/cgroup');result={}
for name in ['memory.current','memory.peak','memory.max','memory.events',
             'pids.current','pids.max','pids.events']:
 result[name]=(root/name).read_text().strip()
print(json.dumps(result))
"""
NODE = r"""
const fs=require('fs'),root='/sys/fs/cgroup/',result={};
for(const name of ['memory.current','memory.peak','memory.max','memory.events',
                  'pids.current','pids.max','pids.events'])
 result[name]=fs.readFileSync(root+name,'utf8').trim();
let zombies=0;
for(const pid of fs.readdirSync('/proc').filter(p=>/^[0-9]+$/.test(p))){
 try{const stat=fs.readFileSync('/proc/'+pid+'/stat','utf8');
  if(stat.slice(stat.lastIndexOf(')')+2).split(' ')[0]==='Z')zombies++;
 }catch{}
}
result.zombie_processes=zombies;
console.log(JSON.stringify(result));
"""


def observe() -> dict[str, object]:
    values: list[dict[str, object]] = []
    for suffix, command in (
        ("pdp-app", ["python", "-c", PYTHON]),
        ("review-chrome", ["node", "-e", NODE]),
    ):
        name = PREFIX + "-" + suffix
        metadata = docker.inspect_container(name)
        host, state = record(metadata["HostConfig"]), record(metadata["State"])
        values.append(
            {
                "name": name,
                "container_id": metadata["Id"],
                "image": metadata["Image"],
                "running": state["Running"],
                "oom_killed": state["OOMKilled"],
                "init_reaper": bool(host.get("Init")),
                "memory_limit_bytes": host["Memory"],
                "pids_limit": host["PidsLimit"],
                "cgroup": json.loads(docker.exec(name, command)),
            }
        )
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "target": PREFIX,
        "observations": values,
        "credentials_or_commands_returned": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = observe()
    with args.output.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
