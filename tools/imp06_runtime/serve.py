"""Start one independently provisioned IMP-06 serving workload."""

import argparse
import os
from pathlib import Path
from uuid import UUID

from care_link_domain import ManualError
from care_link_workload_trust import UnixFenceClient

from tools.imp02_application.config import public_key
from tools.imp03_runtime.compose import Composition
from tools.imp03_runtime.config import integer, load, text

from .manual_roles import ManualRoleAssistance
from .provider_stop import ProviderStopAuthority
from .release_custody import ReleaseCustody
from .release_custody_records import ReleaseObservation
from .resources import load_knowledge_resources
from .role_process import (
    backend_verifier,
    serve_backend,
    start_host_bridge,
    start_inference,
    start_runtime,
)
from .serving_release import load_serving_trust, read_release_record


def _path(parser: argparse.ArgumentParser, name: str) -> None:
    parser.add_argument("--" + name, type=Path, required=True)


def _backend(parser: argparse.ArgumentParser) -> None:
    _path(parser, "backend-socket")
    _path(parser, "fence-socket")
    parser.add_argument("--proxy-uid", type=int, required=True)
    parser.add_argument("--fence-uid", type=int, required=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _path(parser, "release-ledger")
    _path(parser, "trust")
    _path(parser, "observation")
    parser.add_argument("--custody-uid", type=int, required=True)
    parser.add_argument("--boot-id", required=True)
    roles = parser.add_subparsers(dest="role", required=True)
    runtime = roles.add_parser("runtime")
    _path(runtime, "core-socket")
    runtime.add_argument("--once", action="store_true")
    inference = roles.add_parser("inference")
    _backend(inference)
    _path(inference, "data-socket")
    _path(inference, "bridge-socket")
    bridge = roles.add_parser("host-inference-bridge")
    _backend(bridge)
    _path(bridge, "artifact-directory")
    _path(bridge, "model-index")
    _path(bridge, "lmstudio-token-file")
    core = roles.add_parser("core")
    _path(core, "config")
    _path(core, "inference-socket")
    data = roles.add_parser("data")
    _path(data, "config")
    _path(data, "stop-receipts")
    _path(data, "stop-public-key")
    data.add_argument("--stop-issuer", required=True)
    data.add_argument("--stop-owner-uid", type=int, required=True)
    data.add_argument("--bridge-generation", required=True)
    args = parser.parse_args()
    try:
        if args.custody_uid < 0 or args.custody_uid == os.geteuid():
            raise ValueError("release writer and serving workload need distinct custody")
        if str(UUID(args.boot_id)) != args.boot_id:
            raise ValueError("canonical supervisor-generated boot ID required")
        if not all(
            path.is_absolute() for path in (args.release_ledger, args.trust, args.observation)
        ):
            raise ValueError("absolute authorized input paths required")
        custody = ReleaseCustody(
            args.release_ledger,
            trust=load_serving_trust(args.trust, owner_uid=args.custody_uid),
            owner_uid=args.custody_uid,
        )
        observation = read_release_record(ReleaseObservation, args.observation)
        bindings = custody.serving_bindings(observation, instance=args.role, boot_id=args.boot_id)
        bindings.release("worker_summary")
        if args.role == "runtime":
            start_runtime(bindings, core_socket=args.core_socket, once=args.once)
            return
        cfg = None
        if args.role in {"core", "data"}:
            cfg = load(args.config)
            if text(cfg, "role") != args.role or integer(cfg, "uid") != os.geteuid():
                raise ValueError("owner-specific manual role configuration required")
            args.backend_socket = Path(text(cfg, "backend_socket"))
            args.fence_socket = Path(text(cfg, "fence_socket"))
            args.fence_uid = integer(cfg, "fence_uid")
            args.proxy_uid = integer(cfg, "proxy_uid")
        if (
            args.fence_uid < 0
            or len({os.geteuid(), args.proxy_uid, args.fence_uid, args.custody_uid}) != 4
        ):
            raise ValueError("workload, proxy, fence and release writer need distinct custody")
        verifier = backend_verifier(
            args.role,
            proxy_uid=args.proxy_uid,
            fence_socket=args.fence_socket,
            fence_uid=args.fence_uid,
            training_enabled=cfg is not None and cfg.get("training_enabled") is True,
        )
        if cfg is not None:
            fences = UnixFenceClient(args.fence_socket, args.fence_uid)
            knowledge = load_knowledge_resources()
            if args.role == "data":
                if not args.stop_public_key.is_absolute() or args.stop_owner_uid in {
                    os.geteuid(),
                    args.proxy_uid,
                    args.fence_uid,
                }:
                    raise ValueError("independent host stop issuer and key required")
                ai = ManualRoleAssistance(
                    bindings,
                    verifier,
                    fences,
                    knowledge,
                    provider_stop=ProviderStopAuthority(
                        args.stop_receipts,
                        public_key(str(args.stop_public_key)),
                        fences,
                        issuer=args.stop_issuer,
                        target=custody.trust.target,
                        owner_uid=args.stop_owner_uid,
                        current_generation=args.bridge_generation,
                    ),
                )
            else:
                ai = ManualRoleAssistance(
                    bindings, verifier, fences, knowledge, inference_socket=args.inference_socket
                )
            serve_backend(
                Composition(cfg, ai=ai),
                backend_socket=args.backend_socket,
                proxy_uid=args.proxy_uid,
            )
        elif args.role == "inference":
            start_inference(
                bindings,
                verifier,
                backend_socket=args.backend_socket,
                data_socket=args.data_socket,
                bridge_socket=args.bridge_socket,
            )
        else:
            start_host_bridge(
                bindings,
                verifier,
                backend_socket=args.backend_socket,
                artifact_directory=args.artifact_directory,
                model_index=args.model_index,
                lmstudio_token_file=args.lmstudio_token_file,
            )
    except (OSError, ValueError, ManualError):
        raise SystemExit(
            "IMP-06 serving startup denied by configuration or current authority"
        ) from None


if __name__ == "__main__":
    main()
