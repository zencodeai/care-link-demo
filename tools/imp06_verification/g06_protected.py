"""Exercise the fixed provider path from an isolated SPIRE/Envoy inference role."""

import argparse
import hashlib
import hmac
import json
import secrets
import select
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch

from care_link_inference_bridge.bridge import MODEL
from fastapi import Request
from fastapi.testclient import TestClient

from tests.evaluation.qwen_combined_journey import release_artifact
from tests.evaluation.qwen_signed_bridge import stage
from tools.imp06_runtime.bridge import bridge_application
from tools.imp06_verification import role_topology as mesh
from tools.imp06_verification.g06_protected_wire import (
    EXECUTE,
    MESSAGES,
    PAYLOAD,
    TOKENIZE_PATH,
    Record,
    checked_request,
    object_record,
    read_frame,
    tokenize_body,
    write_frame,
)

PREFIX = "care-link-imp06-007-protected"
PROCESS_SOURCE = Path(__file__).with_name("g06_protected_processes.py")
CONTAINER_SOURCES = tuple(
    Path(__file__).with_name(name)
    for name in ("role_topology_processes.py", "g06_protected_wire.py")
)
HOST_ROLE = "host-inference-bridge"
LOCAL_GUARD = "X-Isolated-Qualification"


class Lab(mesh.Lab):
    def run(
        self,
        suffix: str,
        args: list[str],
        mounts: list[str],
        *,
        uid: int = 0,
        groups: tuple[int, ...] = (),
        net: str = "none",
        address: str = "",
        pid: str = "",
        image: str | None = None,
        caps: tuple[str, ...] = (),
        detached: bool = True,
        stdin: str | None = None,
    ) -> str:
        if image is None:
            mounts = [
                *mounts,
                *(
                    f"type=bind,source={path},target=/app/tools/imp06_verification/{path.name},readonly"
                    for path in CONTAINER_SOURCES
                ),
            ]
        return super().run(
            suffix,
            args,
            mounts,
            uid=uid,
            groups=groups,
            net=net,
            address=address,
            pid=pid,
            image=image,
            caps=caps,
            detached=detached,
            stdin=stdin,
        )


def post(lab: Lab, operation: str, body: Record, *, status: int = 200) -> Record:
    response = mesh.post(lab, "inference", HOST_ROLE, operation, body)
    if not mesh.state_matches(response, status, "inference"):
        observed = response.get("status")
        actual = observed if type(observed) is int else "invalid"
        peer = response.get("authenticated_peer")
        verified_role = (
            "inference" if peer == mesh.spiffe("inference") else "other" if peer else "absent"
        )
        raise RuntimeError(
            f"protected provider {operation.rsplit('/', 1)[-1]} expected {status} from inference"
            f" and observed {actual} with verified role {verified_role}"
        )
    return response


def verify_readiness(lab: Lab) -> None:
    """Wait for authenticated route metadata before constructing the host model bridge."""
    bad_body = {**tokenize_body(MESSAGES), "content_digest": "0" * 64}

    def authenticated_malformed_requests() -> str:
        post(lab, EXECUTE, {}, status=400)
        post(lab, TOKENIZE_PATH, bad_body, status=400)
        return "ready"

    mesh.retry(
        authenticated_malformed_requests,
        "inference SVID routes failed authenticated malformed request checks",
        seconds=60,
    )


def qualify(lab: Lab, client: TestClient, guard: str) -> Record:
    body = tokenize_body(MESSAGES)
    with subprocess.Popen(  # noqa: S603
        [  # noqa: S607
            "docker",
            "exec",
            "-i",
            mesh.resource(HOST_ROLE + "-app"),
            "python",
            "/qualification.py",
            "courier",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as courier:
        try:
            mesh.retry(
                lambda: lab.process(HOST_ROLE + "-app", "courier-ready"),
                "private provider courier unavailable",
                seconds=12,
            )
            if courier.stdout is None or courier.stdin is None:
                raise RuntimeError("private courier pipes unavailable")

            def invoke() -> tuple[Record, Record]:
                tokenized = post(lab, TOKENIZE_PATH, body)
                deadline = datetime.now(UTC) + timedelta(seconds=23)
                generated = post(
                    lab,
                    EXECUTE,
                    {
                        "payload": PAYLOAD,
                        "deadline": deadline.isoformat().replace("+00:00", "Z"),
                    },
                )
                return tokenized, generated

            with ThreadPoolExecutor(max_workers=1) as pool:
                running = pool.submit(invoke)
                for operation in (TOKENIZE_PATH, EXECUTE):
                    if not select.select([courier.stdout], [], [], 29)[0]:
                        raise RuntimeError("private provider courier deadline expired")
                    request = checked_request(read_frame(courier.stdout), operation)
                    result = client.post(operation, json=request, headers={LOCAL_GUARD: guard})
                    write_frame(
                        courier.stdin,
                        {
                            "status": result.status_code,
                            "body": result.json() if result.status_code == 200 else None,
                        },
                    )
                tokenized, generated = running.result(timeout=10)
            if courier.wait(timeout=5) != 0:
                raise RuntimeError("private provider courier did not complete cleanly")
        finally:
            if courier.poll() is None:
                courier.kill()

    proof = object_record(tokenized["body"])
    completion = object_record(generated["body"])
    usage = object_record(completion["usage"])
    choices = completion["choices"]
    if not isinstance(choices, list) or len(cast(list[object], choices)) != 1:
        raise RuntimeError("single synthetic generation required")
    choice = object_record(cast(list[object], choices)[0])
    message = object_record(choice["message"])
    if (
        proof["model_identifier"] != MODEL
        or proof["loaded_model_id"] != MODEL
        or completion["model"] != MODEL
        or proof["content_digest"] != body["content_digest"]
        or type(proof["input_tokens"]) is not int
        or proof["input_tokens"] != usage["prompt_tokens"]
        or proof["template_overhead"] != 0
        or choice["finish_reason"] != "stop"
        or json.loads(str(message["content"])) != {"status": "READY"}
    ):
        raise RuntimeError("exact tokenizer and synthetic response did not agree")
    return {
        "model": MODEL,
        "model_window": proof["model_window"],
        "artifact_digest": proof["artifact_digest"],
        "template_digest": proof["template_digest"],
        "tokenizer_digest": proof["tokenizer_digest"],
        "actual_input_tokens": proof["input_tokens"],
        "actual_output_tokens": usage["completion_tokens"],
        "provider_token_count_matches": True,
        "malformed_digest_status": 400,
        "malformed_execute_status": 400,
        "synthetic_json_expected": True,
        "tokenize_svid_digest": tokenized["peer_certificate_digest"],
        "execute_svid_digest": generated["peer_certificate_digest"],
        "authorizing_peer": tokenized["authenticated_peer"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    for argument in ("image-receipt", "artifact-dir", "model-index", "token-file", "output"):
        parser.add_argument("--" + argument, type=Path, required=True)
    parser.add_argument("--run", required=True, action="store_true")
    arguments = parser.parse_args()
    output = cast(Path, arguments.output)
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        parser.error("fresh evidence path in an existing directory required")

    with (
        patch.object(mesh, "PREFIX", PREFIX),
        patch.object(mesh, "LABEL", "care-link.session=" + PREFIX),
        patch.object(mesh, "PROBE_SOURCE", PROCESS_SOURCE),
        patch.dict("os.environ", {"CARE_LINK_JOURNEY_IMAGE_RECEIPT": str(arguments.image_receipt)}),
        TemporaryDirectory(prefix="imp06-007-protected-") as scratch,
    ):
        lab = Lab(arguments.image)
        lab.fresh()
        artifact = release_artifact()
        if artifact.observation.image_digest != lab.image.removeprefix("sha256:"):
            raise ValueError("exact candidate image required")
        try:
            addresses = lab.bootstrap()
            lab.start_roles(addresses)
            verify_readiness(lab)
            custody, epoch, boots = stage(Path(scratch), artifact)
            bindings = custody.qualification_bindings(
                artifact.observation, instance=HOST_ROLE, boot_id=boots[HOST_ROLE]
            )
            guard = secrets.token_urlsafe(32)

            def local_verify(request: Request, role: str) -> bool:
                return role == "inference" and hmac.compare_digest(
                    request.headers.get(LOCAL_GUARD, ""), guard
                )

            app = bridge_application(
                bindings,
                local_verify,
                artifact_directory=arguments.artifact_dir,
                model_index=arguments.model_index,
                lmstudio_token_file=arguments.token_file,
            )
            with TestClient(app) as client:
                observations = qualify(lab, client, guard)
            custody.disable(expected_epoch=epoch)
        finally:
            cleanup = lab.cleanup()
            lab.fresh()

    evidence: Record = {
        "state": "passed",
        "recorded_at": datetime.now(UTC).isoformat(),
        "candidate_image": lab.image,
        "qualification_bundle_digest": artifact.bundle_digest,
        "pins": {key: lab.images[key] for key in ("envoy", "spire_server", "spire_agent")},
        "harness_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), PROCESS_SOURCE, Path(mesh.__file__), *CONTAINER_SOURCES)
        },
        "cleanup": cleanup,
        "observations": observations,
        "limits": [
            "Real inference SVID crossed disposable Envoy mTLS and protected Unix bridge ingress.",
            "Private Unix socket and Docker exec stdio transported the fixed synthetic case.",
            "Relay frames held fixed synthetic content and no credentials or destinations.",
            "Business workflow, participant serving and provider restart are separate evidence.",
        ],
    }
    with output.open("x") as stream:
        json.dump(evidence, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"state": "passed", "output": str(output)}))


if __name__ == "__main__":
    main()
