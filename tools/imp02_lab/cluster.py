"""Create only the named disposable cluster; never change global Docker/kube settings."""

import json
import re

from .commands import kubectl, private_json, run, verify_file, verify_session
from .model import CLUSTER, SESSION, LabInputs


def disable_pod_ipv6(template: str) -> str:
    """Disable the unqualified IP family in each new pod's own network namespace.

    Calico's reviewed template contains one unquoted MTU placeholder. Preserve
    it while parsing the known plugin chain; never edit a node/host sysctl here.
    Existing network namespaces must be recreated and observed separately.
    """
    marker = "__CNI_MTU__"
    if template.count(marker) != 1:
        raise ValueError("reviewed Calico MTU placeholder required")
    value = json.loads(template.replace(marker, json.dumps(marker)))
    plugins = value.get("plugins")
    if not isinstance(plugins, list) or len(plugins) not in (2, 3):
        raise ValueError("reviewed Calico plugin chain required")
    if [item.get("type") for item in plugins[:2]] != ["calico", "portmap"]:
        raise ValueError("unexpected Calico plugin chain")
    tuning = {
        "type": "tuning",
        "sysctl": {
            "net.ipv6.conf.all.disable_ipv6": "1",
            "net.ipv6.conf.default.disable_ipv6": "1",
        },
    }
    if len(plugins) == 3:
        if plugins[2] != tuning:
            raise ValueError("unexpected existing tuning authority")
    else:
        plugins.append(tuning)
    return json.dumps(value, indent=2).replace(json.dumps(marker), marker)


def _ipv6_manifest(source: str) -> str:
    anchor = "  cni_network_config: |-\n"
    if source.count(anchor) != 1:
        raise ValueError("reviewed Calico CNI ConfigMap anchor required")
    start = source.index(anchor) + len(anchor)
    end = source.index("\n---", start)
    lines = source[start:end].splitlines()
    if any(line and not line.startswith("    ") for line in lines):
        raise ValueError("unexpected Calico ConfigMap block boundary")
    template = "\n".join(line[4:] if line else line for line in lines)
    updated = disable_pod_ipv6(template)
    return source[:start] + "\n".join("    " + line for line in updated.splitlines()) + source[end:]


def configuration(inputs: LabInputs) -> dict[str, object]:
    return {
        "kind": "Cluster",
        "apiVersion": "kind.x-k8s.io/v1alpha4",
        "networking": {
            "disableDefaultCNI": True,
            "podSubnet": "192.168.0.0/16",
            "serviceSubnet": "10.96.0.0/16",
            "ipFamily": "ipv4",
            "apiServerAddress": "127.0.0.1",
        },
        "kubeadmConfigPatches": ["kind: KubeletConfiguration\nserverTLSBootstrap: true\n"],
        "nodes": [
            {
                "role": "control-plane",
                "image": inputs.image("node"),
                "extraPortMappings": [
                    {
                        "containerPort": 30441,
                        "hostPort": 18443,
                        "listenAddress": "127.0.0.1",
                        "protocol": "TCP",
                    },
                    {
                        "containerPort": 30443,
                        "hostPort": 20443,
                        "listenAddress": "127.0.0.1",
                        "protocol": "TCP",
                    },
                ],
            }
        ],
    }


def calico(inputs: LabInputs) -> str:
    verify_file(inputs.calico_manifest, inputs.calico_sha256)
    source = inputs.calico_manifest.read_text()
    # The upstream pinned plain manifest uses these three image roles. Refuse
    # new unreviewed image acquisitions instead of silently accepting a tag.
    images = re.findall(r"(?m)^\s*image:\s*(\S+)\s*$", source)
    if not images:
        raise ValueError("no Calico images found")
    for image in set(images):
        name = image.split(":", 1)[0].rsplit("/", 1)[-1]
        role = {
            "node": "calico_node",
            "calico": "calico",
            "third-party-cni-plugins": "calico_plugins",
            "kube-controllers": "calico_controllers",
        }.get(name)
        if role is None:
            raise ValueError("unreviewed Calico image role")
        source = source.replace(image, inputs.image(role))
    return _ipv6_manifest(source)


def create(inputs: LabInputs) -> None:
    verify_file(inputs.kind_binary, inputs.kind_sha256)
    if inputs.state_dir.exists() and any(inputs.state_dir.iterdir()):
        raise ValueError("new empty temporary lab state directory required")
    inputs.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    inputs.state_dir.chmod(0o700)
    private_json(inputs.state_dir / "lease.json", {"session": SESSION, "cluster": CLUSTER})
    kind_config = inputs.state_dir / "kind.json"
    private_json(kind_config, configuration(inputs))
    existing = run([str(inputs.kind_binary), "get", "clusters"]).splitlines()
    if CLUSTER in existing:
        raise ValueError("named cluster already exists; refusing to adopt it")
    run(
        [
            str(inputs.kind_binary),
            "create",
            "cluster",
            "--name",
            CLUSTER,
            "--config",
            str(kind_config),
            "--kubeconfig",
            str(inputs.state_dir / "kubeconfig"),
            "--wait",
            "0s",
        ],
        timeout=600,
    )
    verify_session(inputs)
    kubectl(inputs, "apply", "--server-side", "-f", "-", stdin=calico(inputs))
    kubectl(inputs, "wait", "--for=condition=Ready", "nodes", "--all", "--timeout=300s")
    private_json(
        inputs.state_dir / "node-observation.json",
        json.loads(kubectl(inputs, "get", "nodes", "-o", "json")),
    )


def destroy(inputs: LabInputs) -> None:
    verify_file(inputs.kind_binary, inputs.kind_sha256)
    verify_session(inputs)
    run(
        [
            str(inputs.kind_binary),
            "delete",
            "cluster",
            "--name",
            CLUSTER,
            "--kubeconfig",
            str(inputs.state_dir / "kubeconfig"),
        ],
        timeout=180,
    )
