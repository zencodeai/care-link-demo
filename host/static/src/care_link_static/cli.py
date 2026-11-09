"""Run the independent public process. Review key is external public material."""

import argparse
from pathlib import Path

import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .app import create_app
from .publication import PublicationStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--review-public-key", type=Path)
    parser.add_argument("--allow-owner-demo", action="store_true")
    parser.add_argument("--port", type=int, default=8023)
    args = parser.parse_args()
    store = None
    if args.directory and args.review_public_key:
        key = load_pem_public_key(args.review_public_key.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            parser.error("An Ed25519 review public key is required")
        store = PublicationStore(args.directory, key, allow_owner_demo=args.allow_owner_demo)
    elif args.directory or args.review_public_key:
        parser.error("Supply both directory and review public key")
    uvicorn.run(
        create_app(store, allow_owner_demo=args.allow_owner_demo),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
    )
