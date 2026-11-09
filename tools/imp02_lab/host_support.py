"""Host-help processes outside kind, with separately admitted SPIRE Unix identity."""

from .model import CLUSTER, SESSION, LabInputs

PROJECT = CLUSTER + "-host"
AGENT_ID = "spiffe://care-link.demo/host/imp02-002"


def agent_config() -> str:
    return f'''agent {{
  trust_domain = "care-link.demo"
  data_dir = "/run/spire/data"
  server_address = "{CLUSTER}-control-plane"
  server_port = "30881"
  socket_path = "/run/spire/sockets/agent.sock"
  trust_bundle_path = "/config/bundle.crt"
  join_token_file = "/config/join.token"
  log_level = "WARN"
}}
plugins {{
  NodeAttestor "join_token" {{ plugin_data {{ }} }}
  KeyManager "memory" {{ plugin_data {{ }} }}
  WorkloadAttestor "unix" {{ plugin_data {{ }} }}
}}
'''


def _volume(name: str, target: str, readonly: bool = False) -> dict[str, object]:
    return {"type": "volume", "source": name, "target": target, "read_only": readonly}


def seed_script() -> str:
    records = [
        ("backend", 21013, 21002, 0o710),
        ("outbound", 21002, 21013, 0o710),
        ("spool", 21013, 21013, 0o700),
        ("application-config", 21013, 21013, 0o700),
        ("proxy-config", 21002, 21002, 0o700),
        ("agent-config", 0, 0, 0o700),
        ("agent-data", 0, 0, 0o700),
        ("workload-api", 0, 0, 0o755),
        ("admin", 21002, 21002, 0o700),
    ]
    copies = [
        ("help.json", "application-config", "help.json", 21013),
        ("identity-signing.pub", "application-config", "identity-signing.pub", 21013),
        ("envoy.json", "proxy-config", "envoy.json", 21002),
        ("help.crt", "proxy-config", "help.crt", 21002),
        ("help.key", "proxy-config", "help.key", 21002),
        ("agent.conf", "agent-config", "agent.conf", 0),
        ("join.token", "agent-config", "join.token", 0),
        ("bundle.crt", "agent-config", "bundle.crt", 0),
    ]
    return "\n".join(
        [
            "import os,pathlib",
            f"records={records!r}",
            "for name,uid,gid,mode in records:",
            " p=pathlib.Path('/volumes',name);os.chown(p,uid,gid);p.chmod(mode)",
            f"copies={copies!r}",
            "for source,volume,name,uid in copies:",
            " p=pathlib.Path('/volumes',volume,name)",
            " fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)",
            " with os.fdopen(fd,'wb') as out:",
            "  out.write(pathlib.Path('/sources',source).read_bytes())",
            "  out.flush();os.fsync(out.fileno())",
            " os.chown(p,uid,uid);p.chmod(0o600)",
        ]
    )


def composition(inputs: LabInputs) -> dict[str, object]:
    volume_names = [
        "backend",
        "outbound",
        "spool",
        "application-config",
        "proxy-config",
        "agent-config",
        "agent-data",
        "workload-api",
        "admin",
    ]
    common: dict[str, object] = {
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": 96,
        "mem_limit": "256m",
        "cpus": "1.0",
        "labels": {"care-link.session": SESSION},
    }
    result = {
        "name": PROJECT,
        "services": {
            "seed": common
            | {
                "image": inputs.image("python"),
                "container_name": PROJECT + "-seed",
                "user": "0:0",
                "network_mode": "none",
                "cap_add": ["CHOWN", "FOWNER", "DAC_OVERRIDE"],
                "command": ["python", "-c", "import time;time.sleep(86400)"],
                "tmpfs": ["/sources:rw,noexec,nosuid,size=1048576,mode=0700"],
                "volumes": [_volume(name, "/volumes/" + name) for name in volume_names],
            },
            "agent": common
            | {
                "image": inputs.image("spire_agent"),
                "container_name": PROJECT + "-agent",
                "user": "0:0",
                "networks": ["kind"],
                "command": ["-config", "/config/agent.conf"],
                "volumes": [
                    _volume("agent-config", "/config", True),
                    _volume("agent-data", "/run/spire/data"),
                    _volume("workload-api", "/run/spire/sockets"),
                ],
            },
            "proxy": common
            | {
                "image": inputs.image("envoy"),
                "container_name": PROJECT + "-proxy",
                "user": "21002:21002",
                "networks": ["kind"],
                "pid": "service:agent",
                "depends_on": ["agent"],
                "ports": ["127.0.0.1:19443:8444"],
                "command": [
                    "-c",
                    "/config/envoy.json",
                    "--disable-hot-restart",
                    "--log-level",
                    "warning",
                ],
                "volumes": [
                    _volume("backend", "/run/care-link/backend", True),
                    _volume("outbound", "/run/care-link/outbound"),
                    _volume("proxy-config", "/config", True),
                    _volume("admin", "/run/care-link/admin"),
                    _volume("workload-api", "/run/spire/sockets", True),
                ],
            },
            "help": common
            | {
                "image": inputs.image("application"),
                "container_name": PROJECT + "-help",
                "entrypoint": [],
                "user": "21013:21013",
                "group_add": ["21002"],
                "network_mode": "none",
                "pid": "service:agent",
                "depends_on": ["agent"],
                "command": [
                    "python",
                    "-m",
                    "tools.imp02_application",
                    "--role",
                    "help",
                    "--config",
                    "/config/help.json",
                ],
                "volumes": [
                    _volume("backend", "/run/care-link/backend"),
                    _volume("outbound", "/run/care-link/outbound", True),
                    _volume("application-config", "/config", True),
                    _volume("spool", "/spool"),
                ],
            },
        },
        "networks": {"kind": {"external": True, "name": "kind"}},
        "volumes": {
            name: {"name": PROJECT + "-" + name, "labels": {"care-link.session": SESSION}}
            for name in volume_names
        },
    }

    from .certificates import host_diagnostic

    result["services"]["certificate-probe"] = host_diagnostic(inputs)
    return result
