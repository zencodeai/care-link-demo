"""Immutable signed artifact registration and exact independent human reviews."""

import base64
import binascii
import hashlib
from datetime import timedelta
from typing import cast

from care_link_domain import Actor, ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..engine import Engine
from ..store import Record, Transaction, instant, text
from ..values import Outcome, canonical, dt, object_value
from .authority import current_human, human_account
from .classification import change_class, required_authorities
from .projections import artifact_view, command, required


def verified_candidate(tx: Transaction, data: Record) -> tuple[Record, str]:
    candidate = required(tx, "gov_candidate", text(data, "digest"))
    signer = required(tx, "gov_signer", text(candidate, "key_id"))
    manifest = object_value(candidate["manifest"])
    if signer["active"] is not True or candidate["metadata"] != data:
        raise ManualError("governance.artifact_provenance_invalid")
    if set(manifest) != {
        "changed_paths",
        "compatible_serving_generation",
        "mode",
        "rollback_trigger",
        "required_evidence",
    }:
        raise ManualError("governance.manifest_invalid")
    paths = manifest["changed_paths"]
    if (
        not isinstance(paths, list)
        or not 1 <= len(cast(list[object], paths)) <= 128
        or not all(isinstance(p, str) and 0 < len(p) <= 256 for p in cast(list[object], paths))
    ):
        raise ManualError("governance.manifest_invalid")
    if manifest["mode"] not in {"normal", "ai_disabled", "restricted", "quarantine"}:
        raise ManualError("governance.manifest_invalid")
    try:
        payload = base64.b64decode(text(candidate, "payload"), validate=True)
        if len(payload) > 1048576 or hashlib.sha256(payload).hexdigest() != data["digest"]:
            raise ManualError("governance.artifact_digest_invalid")
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(text(signer, "public_key"), validate=True)
        )
        body = {
            "metadata": {k: v for k, v in data.items() if k != "signature"},
            "manifest": manifest,
        }
        key.verify(
            base64.b64decode(text(data, "signature"), validate=True), canonical(body).encode()
        )
    except (ValueError, binascii.Error, InvalidSignature) as error:
        raise ManualError("governance.artifact_signature_invalid") from error
    domains = cast(list[str], data["governed_domains"])
    classification = change_class(text(data, "kind"), domains, cast(list[str], paths))
    required_evidence = manifest["required_evidence"]
    if (
        not isinstance(required_evidence, list)
        or not required_evidence
        or not set(cast(list[str], required_evidence)).issubset(
            cast(list[str], data["evidence_digests"])
        )
    ):
        raise ManualError("governance.evidence_missing")
    if classification == "C3" and (
        not manifest["rollback_trigger"] or data["content_class"] != "stub"
    ):
        raise ManualError("governance.synthetic_high_risk_evidence_required")
    return manifest, classification


def reviews_current(tx: Transaction, artifact: Record, now: object) -> None:
    from ..values import dt

    current_time = dt(now)
    human_account(tx, text(artifact, "proposer_account_id"))
    metadata = object_value(artifact["metadata"])
    needed = required_authorities(
        text(artifact, "change_class"), cast(list[str], metadata["governed_domains"])
    )
    rows = tx.rows("gov_review", artifact_digest=artifact["digest"], limit=100)
    if len(rows) == 100:
        raise ManualError("governance.review_history_limit", 503)
    latest: dict[str, Record] = {}
    for row in sorted(rows, key=lambda r: instant(r, "created_at")):
        latest[text(row, "authority_class")] = row
    seen: set[str] = {text(artifact, "proposer_human_id")}
    for authority in sorted(needed):
        review = latest.get(authority)
        if (
            review is None
            or review["decision"] != "accept"
            or instant(review, "expires_at") <= current_time
        ):
            raise ManualError("governance.missing_current_reviews", 409)
        if artifact["last_activated_at"] is not None and instant(review, "created_at") <= instant(
            artifact, "last_activated_at"
        ):
            raise ManualError("governance.rollback_fresh_reviews_required", 409)
        human = human_account(tx, text(review, "reviewer_account_id"), authority)
        human_id = text(human, "human_id")
        if human_id != review["reviewer_human_id"] or human_id in seen:
            raise ManualError("governance.independent_human_required")
        seen.add(human_id)


class Artifacts(Engine):
    def artifact_register(self, actor: Actor, key: str, data: Record) -> Record:
        def register(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            human = current_human(tx, current, self.clock(), "technical")
            manifest, classification = verified_candidate(tx, body)
            old = tx.get("gov_artifact", text(body, "digest"))
            if old:
                if old["metadata"] != body:
                    raise ManualError("governance.immutable_artifact", 409)
                return Outcome("ArtifactView", artifact_view(old))
            row: Record = {
                "digest": body["digest"],
                "kind": body["kind"],
                "version": body["version"],
                "state": "review_pending",
                "metadata": body,
                "manifest": manifest,
                "change_class": classification,
                "proposer_account_id": current.account_id,
                "proposer_human_id": human["human_id"],
                "created_at": self.clock(),
                "last_activated_at": None,
            }
            tx.put("gov_artifact", row)
            return Outcome("ArtifactView", artifact_view(row))

        return self._run(
            actor,
            "artifact_register",
            key,
            data,
            None,
            register,
            contract="ArtifactRegister",
            replay=register,
        )

    def artifact_review(self, actor: Actor, key: str, data: Record) -> Record:
        def review(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            human = current_human(tx, current, self.clock(), text(body, "authority_class"))
            artifact = required(tx, "gov_artifact", text(body, "artifact_digest"))
            if human["human_id"] == artifact["proposer_human_id"]:
                raise ManualError("governance.independent_human_required")
            if body["change_class"] != artifact["change_class"]:
                raise ManualError("governance.change_class_floor", 422)
            expiry = dt(body["expires_at"]) if body["expires_at"] else None
            if expiry is None or not self.clock() < expiry <= self.clock() + timedelta(days=1):
                raise ManualError("governance.review_expiry_required", 422)
            old = tx.get("gov_review", key)
            if old is None:
                tx.put(
                    "gov_review",
                    {
                        "id": key,
                        "artifact_digest": artifact["digest"],
                        "authority_class": body["authority_class"],
                        "reviewer_account_id": current.account_id,
                        "reviewer_human_id": human["human_id"],
                        "decision": body["decision"],
                        "evidence_digest": body["evidence_digest"],
                        "expires_at": expiry,
                        "created_at": self.clock(),
                    },
                )
                artifact["state"] = "rejected" if body["decision"] == "reject" else "review_pending"
                tx.put("gov_artifact", artifact)
            return Outcome("CommandResult", command(key, key), key)

        return self._run(
            actor,
            "artifact_review",
            key,
            data,
            None,
            review,
            contract="ArtifactReview",
            replay=review,
        )

    def artifact_context(self, actor: Actor, artifact_digest: str) -> Record:
        def read(
            tx: Transaction, current: Actor, _body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock())
            artifact = required(tx, "gov_artifact", artifact_digest)
            metadata = object_value(artifact["metadata"])
            manifest, classification = verified_candidate(tx, metadata)
            authorities = sorted(
                required_authorities(classification, cast(list[str], metadata["governed_domains"]))
            )
            rows = tx.rows("gov_review", artifact_digest=artifact_digest, limit=100)
            if len(rows) == 100:
                raise ManualError("governance.review_history_limit", 503)
            latest: dict[str, Record] = {}
            for row in sorted(rows, key=lambda r: instant(r, "created_at")):
                latest[text(row, "authority_class")] = row
            missing: list[str] = []
            seen = {text(artifact, "proposer_human_id")}
            for name in authorities:
                receipt = latest.get(name)
                valid = False
                if (
                    receipt
                    and receipt["decision"] == "accept"
                    and instant(receipt, "expires_at") > self.clock()
                ):
                    try:
                        human = human_account(tx, text(receipt, "reviewer_account_id"), name)
                        valid = (
                            human["human_id"] == receipt["reviewer_human_id"]
                            and human["human_id"] not in seen
                            and (
                                artifact["last_activated_at"] is None
                                or instant(receipt, "created_at")
                                > instant(artifact, "last_activated_at")
                            )
                        )
                        if valid:
                            seen.add(text(human, "human_id"))
                    except ManualError:
                        valid = False
                if not valid:
                    missing.append(name)
            control = required(tx, "control", "demo")
            return Outcome(
                "GovernanceArtifactContext",
                {
                    "artifact": artifact_view(artifact),
                    "source_revision": metadata["source_revision"],
                    "change_class": classification,
                    "governed_domains": metadata["governed_domains"],
                    "changed_paths": manifest["changed_paths"],
                    "required_authorities": authorities,
                    "missing_authorities": missing,
                    "evidence_digests": metadata["evidence_digests"],
                    "previous_digest": control["bundle_digest"],
                    "payload_digest": artifact_digest,
                },
            )

        return self._run(
            actor, "artifact_context", None, {"artifact_digest": artifact_digest}, None, read
        )
