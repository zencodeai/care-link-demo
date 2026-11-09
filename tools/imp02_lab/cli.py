"""Explicit operator CLI; source rendering and live resource mutation are separate."""

import argparse
import json
from pathlib import Path

from . import applications, cluster, csi, dependencies, host_support, network, probes, routes, spire
from .commands import kubectl, private_json, verify_session
from .model import NAMESPACE, load_inputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "create",
            "destroy",
            "render-network",
            "apply-network",
            "probe-network",
            "render-dependencies",
            "apply-dependencies",
            "render-spire",
            "apply-spire",
            "render-applications",
            "apply-applications",
            "render-seed",
            "apply-seed",
            "render-host",
        ),
    )
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--host-probe-ip")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    inputs = load_inputs(args.inputs)
    if (
        args.command in {"create", "destroy"} or args.command.startswith("apply-")
    ) and not args.execute:
        parser.error("live command requires explicit --execute and the current resource lease")
    if args.command == "create":
        cluster.create(inputs)
    elif args.command == "destroy":
        cluster.destroy(inputs)
    elif args.command == "probe-network":
        if not args.host_probe_ip or args.output is None:
            parser.error("exact active-control IP and explicit evidence --output required")
        result = probes.observe(inputs, args.host_probe_ip)
        private_json(args.output, result)
        if result["status"] != "passed":
            raise SystemExit(1)
    elif args.command == "render-host":
        if args.output is None:
            parser.error("explicit private --output required")
        private_json(args.output, host_support.composition(inputs))
    else:
        component = args.command.split("-", 1)[1]
        if component == "network":
            if not args.host_probe_ip:
                parser.error("exact isolated active-control --host-probe-ip required")
            manifests = [network.namespace(), *network.manifests(inputs, args.host_probe_ip)]
        elif component == "dependencies":
            manifests = [network.namespace(), *dependencies.manifests(inputs)]
        elif component == "spire":
            manifests = [*spire.manifests(inputs), *csi.manifests(inputs)]
        elif component == "seed":
            manifests = [applications.seed(inputs)]
        else:
            manifests = [*applications.manifests(inputs), *routes.manifests()]
        rendered = {"apiVersion": "v1", "kind": "List", "items": manifests}
        if args.command.startswith("render-"):
            if args.output is None:
                parser.error("explicit private --output required")
            private_json(args.output, rendered)
        else:
            verify_session(inputs)
            kubectl(inputs, "apply", "-f", "-", stdin=json.dumps(rendered))
            if component == "network":
                kubectl(
                    inputs,
                    "-n",
                    NAMESPACE,
                    "wait",
                    "--for=condition=Ready",
                    "pod",
                    "--selector=care-link.fixture=network-control",
                    "--timeout=120s",
                )


if __name__ == "__main__":
    main()
