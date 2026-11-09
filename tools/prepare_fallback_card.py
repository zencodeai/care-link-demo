"""Compile accepted card bytes, or publish the explicitly scoped owner-demo profile.

The generated key signs local artifact integrity. It is not a human signature,
independent review, participant admission or a G-02 acceptance receipt.
"""

import argparse
import base64
import hashlib
import json
import os
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid5

from care_link_static import Publication, PublicationStore, PublicText, Review
from care_link_static.publication import canonical, digest, instant, unique
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "doc/IMP/slices/IMP-02-identity-trust-and-fallback/sessions/001-implementation"
ACCEPTANCE = SESSION / "decisions/2026-11-08-first-fallback-card-content-acceptance.json"
DRAFTS = SESSION / "fallback/first-card"
TRANSFORMATIONS = {
    "en-CA": (
        "**Draft for independent review — not published.**",
        "Source details checked for drafting on 2026-11-08. Independent factual, language and "
        "accessibility review is pending. ",
        "No person is contacted automatically by CARE-Link.",
    ),
    "fr-CA": (
        "**Version provisoire pour révision indépendante — non publiée.**",
        "Renseignements vérifiés pour la préparation de cette version le 2026-11-08. La révision "
        "indépendante des faits, de la langue et de l’accessibilité reste à faire. ",
        "CARE-Link ne contacte personne automatiquement.",
    ),
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def accepted_refs() -> list[dict[str, str]]:
    decision = cast(dict[str, object], json.loads(ACCEPTANCE.read_text(), object_pairs_hook=unique))
    refs = cast(list[dict[str, str]], decision["accepted_artifact_refs"])
    expected = {
        str((DRAFTS / name).relative_to(ROOT))
        for name in ("card.en-CA.md", "card.fr-CA.md", "sources.json")
    }
    if {reference["path"] for reference in refs} != expected:
        raise ValueError("Unexpected accepted source set")
    for reference in refs:
        if sha256((ROOT / reference["path"]).read_bytes()) != reference["sha256"]:
            raise ValueError("Accepted content bytes changed; review is required")
    return refs


def prepare() -> tuple[dict[str, object], dict[str, object]]:
    refs = accepted_refs()
    texts: list[PublicText] = []
    changes: list[dict[str, object]] = []
    for locale, (banner, provenance, retained) in TRANSFORMATIONS.items():
        raw = (DRAFTS / f"card.{locale}.md").read_text()
        title, separator, body = raw.partition("\n\n")
        if not separator or not title.startswith("# "):
            raise ValueError("Accepted source title is not the expected Markdown shape")
        if body.count(banner) != 1 or body.count(provenance + retained) != 1:
            raise ValueError("Accepted drafting labels do not match the explicit conversion")
        body = body.replace(banner + "\n\n", "", 1).replace(provenance + retained, retained, 1)
        value = PublicText(locale, title.removeprefix("# "), body.strip() + "\n")
        texts.append(value)
        changes.append(
            {
                "locale": locale,
                "title_presentation": "Move the exact title text into page title and H1",
                "removed_draft_banner": banner,
                "removed_authoring_provenance": provenance,
                "retained_fixed_no_autonomous_contact_statement": retained,
                "content_sha256": sha256(value.text.encode()),
            }
        )
    artifact = digest([value.wire() for value in texts])
    candidate: dict[str, object] = {
        "format_version": "public-text-candidate-1",
        "accepted_decision": {
            "path": str(ACCEPTANCE.relative_to(ROOT)),
            "sha256": sha256(ACCEPTANCE.read_bytes()),
        },
        "texts": [value.wire() for value in texts],
        "artifact_digest": artifact,
        "review_status": "unsigned_final_candidate",
        "participant_admission": False,
    }
    delta: dict[str, object] = {
        "format_version": "accepted-card-conversion-1",
        "accepted_sources": refs,
        "transformations": changes,
        "presentation": "Escaped semantic headings, paragraphs, lists, bold and allowlisted "
        "HTTPS/tel/sms anchors; responsive CSS with exact CSP hash",
        "added_runtime_owner_notice": "Only the explicitly enabled owner-review profile displays "
        "a separate local-demo/no-independent-review/no-admission notice",
        "artifact_digest": artifact,
        "candidate_sha256": sha256(canonical(candidate)),
        "authority": "Mechanical conversion only. Earlier Markdown acceptance is not a signature "
        "or final-page review of these new bytes. No stage acceptance is inferred.",
    }
    return candidate, delta


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def owner_key(path: Path) -> Ed25519PrivateKey:
    if path.exists():
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError("Owner integrity key must be a private regular file")
        key = load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Ed25519 integrity key required")
        return key
    key = Ed25519PrivateKey.generate()
    write_new(path, key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    return key


def publish_owner(args: argparse.Namespace) -> dict[str, object]:
    candidate, _delta = prepare()
    supplied: object = json.loads(args.candidate.read_text(), object_pairs_hook=unique)
    if supplied != candidate:
        raise ValueError("Candidate differs from the mechanically converted accepted content")
    owner = str(UUID(args.owner_account_id))
    if owner != args.owner_account_id:
        raise ValueError("Canonical UUID for the actual main account is required")
    operation = str(UUID(args.operation_id))
    if operation != args.operation_id:
        raise ValueError("Canonical operation UUID is required")
    verified = instant(args.verified_at)
    due = instant(args.review_due_at)
    if not verified < due <= verified + timedelta(days=30):
        raise ValueError("Owner review must follow the approved at-most-30-day cadence")
    texts = cast(list[dict[str, str]], candidate["texts"])
    receipt = str(uuid5(UUID(operation), "owner-demo-publication-review"))
    review = Review(
        receipt,
        owner,
        owner,
        cast(str, candidate["artifact_digest"]),
        args.verified_at,
        args.review_due_at,
        "",
        "owner_review_local_demo",
    )
    key = owner_key(args.integrity_private_key)
    signature = base64.b64encode(key.sign(canonical(review.payload()))).decode()
    publication = Publication(
        (PublicText(**texts[0]), PublicText(**texts[1])), replace(review, signature=signature)
    )
    store = PublicationStore(args.directory, key.public_key(), allow_owner_demo=True)
    current = store.publish(publication, args.expected_current_digest, owner, operation)
    public_path = args.integrity_private_key.with_suffix(".public.pem")
    public_bytes = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    if public_path.exists():
        if public_path.is_symlink() or public_path.read_bytes() != public_bytes:
            raise ValueError("Existing integrity public key differs")
    else:
        write_new(public_path, public_bytes)
    return {
        "review_profile": current.review.profile,
        "artifact_digest": current.artifact_digest,
        "receipt_id": receipt,
        "integrity_public_key": str(public_path),
        "independent_review": False,
        "human_signature_claim": False,
        "participant_admission": False,
        "canonical_independent_manifest": "unavailable",
        "owner_manifest_path": "/demo-static/v1/manifest",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    compile_command = commands.add_parser("prepare")
    compile_command.add_argument("--output", type=Path, required=True)
    compile_command.add_argument("--delta", type=Path, required=True)
    publish_command = commands.add_parser("publish-owner-demo")
    publish_command.add_argument("--candidate", type=Path, required=True)
    publish_command.add_argument("--directory", type=Path, required=True)
    publish_command.add_argument("--owner-account-id", required=True)
    publish_command.add_argument("--operation-id", required=True)
    publish_command.add_argument("--integrity-private-key", type=Path, required=True)
    publish_command.add_argument("--verified-at", required=True)
    publish_command.add_argument("--review-due-at", required=True)
    publish_command.add_argument("--expected-current-digest")
    args = parser.parse_args()
    if args.command == "prepare":
        candidate, delta = prepare()
        write_new(args.output, canonical(candidate))
        write_new(args.delta, canonical(delta))
        print(
            json.dumps(
                {
                    "artifact_digest": candidate["artifact_digest"],
                    "status": "unsigned_final_candidate",
                    "participant_admission": False,
                }
            )
        )
    else:
        print(json.dumps(publish_owner(args)))


if __name__ == "__main__":
    main()
