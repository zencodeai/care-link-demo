"""Per-operation certificate, route and live restrictive-fence verification."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, unquote_to_bytes
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

from .fence import TrustDenied
from .fence_protocol import FenceReader

IDENTITY = re.compile(r"spiffe://care-link\.demo/[a-z][a-z0-9_-]{0,31}/[a-z][a-z0-9_-]{0,63}\Z")
TASK_ROUTES = frozenset(
    {
        "/internal/v1/tasks/{task_id}/lease",
        "/internal/v1/tasks/{task_id}/renew",
        "/internal/v1/data/assistance/step_lease/{task_id}",
        "/internal/v1/data/assistance/step_renew/{task_id}",
    }
)
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
INFERENCE_ROUTES = frozenset(
    {
        "/internal/v1/broker/inference",
        "/internal/v1/inference/jobs",
        "/internal/v1/inference/execute",
    }
)


@dataclass(frozen=True)
class PeerRule:
    spiffe_id: str
    routes: frozenset[tuple[str, str]]

    def __post_init__(self) -> None:
        if IDENTITY.fullmatch(self.spiffe_id) is None or not self.routes:
            raise ValueError("exact environment/service SPIFFE identity and routes required")
        for method, path in self.routes:
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"} or not canonical_route(path):
                raise ValueError("exact canonical method/path required")
            if path in TASK_ROUTES and method != "POST":
                raise ValueError("task lease routes require POST")


def canonical_path(path: str) -> bool:
    return (
        path.startswith("/")
        and not any(x in path for x in ("%", "?", "#", "\\", "//", "..", "{", "}", "*"))
        and all(32 < ord(x) < 127 for x in path)
    )


def canonical_route(path: str) -> bool:
    """Only four internal task operations have a canonical UUID path segment."""
    return path in TASK_ROUTES or canonical_path(path)


def task_route_pattern(path: str) -> str:
    if path not in TASK_ROUTES:
        raise ValueError("closed task operation template required")
    return "^" + re.escape(path).replace(r"\{task_id\}", UUID_PATTERN) + "$"


def route_matches(routes: frozenset[tuple[str, str]], method: str, path: str) -> bool:
    if not canonical_path(path):
        return False
    return any(
        candidate_method == method
        and (
            candidate == path
            or (candidate in TASK_ROUTES and re.fullmatch(task_route_pattern(candidate), path))
        )
        for candidate_method, candidate in routes
    )


def envoy_path_match(path: str) -> dict[str, object]:
    if path in TASK_ROUTES:
        return {"safe_regex": {"google_re2": {}, "regex": task_route_pattern(path)}}
    if not canonical_path(path):
        raise ValueError("canonical operation route required")
    return {"path": path}


def route_timeout(path: str) -> str:
    # The provider deadline remains thirty seconds. Its three exact transport
    # hops need enough time to carry the completion/unknown receipt; broad
    # metadata/business routes retain their existing ten-second outer ceiling.
    return "40s" if path.startswith("/bff/") or path in INFERENCE_ROUTES else "10s"


def operation_path(method: str, target: str) -> str:
    """Validate the exact path separately from two bounded OIDC query adapters.

    Return only the path for method/path policy matching; transport forwards the
    original target unchanged. No other private operation gains query access.
    """
    path, separator, query = target.partition("?")
    if not canonical_path(path):
        raise TrustDenied("noncanonical operation path")
    if not separator:
        return path
    if (
        method != "GET"
        or len(query) > 8192
        or not query
        or re.search(r"%(?![0-9a-fA-F]{2})", query)
        or any(ord(char) <= 32 or ord(char) >= 127 or char in "#\\" for char in query)
    ):
        raise TrustDenied("invalid operation query")
    match = re.fullmatch(r"/bff/(main|help)/v1/auth/(callback|step-up/proof)", path)
    if match is None:
        raise TrustDenied("query not allowed for operation")
    try:
        pairs = parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=7,
        )
        values = dict(pairs)
        if len(values) != len(pairs) or any(
            any(ord(char) < 32 or ord(char) == 127 for char in value) for value in values.values()
        ):
            raise ValueError("ambiguous query")
        if match[2] == "step-up/proof":
            if (
                set(values) != {"ceremony_id"}
                or str(UUID(values["ceremony_id"])) != values["ceremony_id"]
            ):
                raise ValueError("invalid ceremony query")
        else:
            bounds = {
                "state": 512,
                "code": 2048,
                "iss": 512,
                "error": 128,
                "error_description": 2048,
                "session_state": 128,
            }
            if (
                not set(values) <= bounds.keys()
                or not 32 <= len(values.get("state", "")) <= 512
                or ("code" in values) == ("error" in values)
                or any(not value or len(value) > bounds[key] for key, value in values.items())
            ):
                raise ValueError("invalid callback query")
    except (ValueError, UnicodeError) as error:
        raise TrustDenied("invalid operation query") from error
    return path


@dataclass(frozen=True)
class Admission:
    spiffe_id: str
    fence_generation: int
    certificate_digest: str
    certificate_expires_at: datetime


def _xfcc(raw: str) -> tuple[x509.Certificate, list[x509.Certificate], str]:
    # SANITIZE_SET must produce exactly one peer entry. The configured output
    # excludes Subject/DNS, avoiding ambiguous multi-entry or quoted DN parsing.
    if not raw or len(raw) > 64 * 1024 or any(x in raw for x in (",", "\r", "\n")):
        raise TrustDenied("ambiguous peer certificate")
    fields: dict[str, str] = {}
    for part in raw.split(";"):
        key, separator, value = part.strip().partition("=")
        if not separator or key not in {"By", "Hash", "Cert", "Chain", "URI"} or key in fields:
            raise TrustDenied("invalid peer certificate fields")
        if value.startswith('"'):
            if not value.endswith('"') or '"' in value[1:-1]:
                raise TrustDenied("invalid peer certificate quoting")
            value = value[1:-1]
        elif '"' in value:
            raise TrustDenied("invalid peer certificate quoting")
        fields[key] = value
    if not {"Cert", "URI"} <= fields.keys() or IDENTITY.fullmatch(fields["URI"]) is None:
        raise TrustDenied("missing canonical SPIFFE certificate")
    try:
        pem = unquote_to_bytes(fields["Cert"])
        cert = x509.load_pem_x509_certificate(pem)
        if cert.public_bytes(Encoding.PEM) != pem:
            raise TrustDenied("noncanonical peer certificate")
        uris = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value.get_values_for_type(x509.UniformResourceIdentifier)
        if uris != [fields["URI"]]:
            raise TrustDenied("peer certificate URI mismatch")
        chain = (
            x509.load_pem_x509_certificates(unquote_to_bytes(fields["Chain"]))
            if fields.get("Chain")
            else []
        )
        if chain and chain[0].public_bytes(Encoding.DER) == cert.public_bytes(Encoding.DER):
            chain = chain[1:]
        if len(chain) > 4:
            raise TrustDenied("peer chain too deep")
        actual_hash = hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()
        if "Hash" in fields and fields["Hash"].lower() != actual_hash:
            raise TrustDenied("peer certificate hash mismatch")
        return cert, chain, fields["URI"]
    except (ValueError, x509.ExtensionNotFound) as error:
        raise TrustDenied("invalid peer certificate") from error


class WorkloadEnforcer:
    def __init__(
        self,
        proxy_uid: int,
        trust_roots: tuple[x509.Certificate, ...],
        rules: tuple[PeerRule, ...],
        fences: FenceReader,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        *,
        local_spiffe_id: str | None = None,
    ) -> None:
        if (
            proxy_uid < 0
            or not trust_roots
            or not rules
            or len({x.spiffe_id for x in rules}) != len(rules)
            or (local_spiffe_id is not None and IDENTITY.fullmatch(local_spiffe_id) is None)
        ):
            raise ValueError("explicit proxy UID, trust roots and unique peer rules required")
        self.proxy_uid, self.trust_roots, self.rules, self.fences, self.clock = (
            proxy_uid,
            trust_roots,
            rules,
            fences,
            clock,
        )
        self.local_spiffe_id = local_spiffe_id

    def authorize(self, peer_uid: int | None, method: str, path: str, xfcc: str) -> Admission:
        if peer_uid is None or peer_uid != self.proxy_uid:
            raise TrustDenied("unverified local proxy")
        path = operation_path(method, path)
        cert, intermediates, peer = _xfcc(xfcc)
        if not any(
            rule.spiffe_id == peer and route_matches(rule.routes, method, path)
            for rule in self.rules
        ):
            raise TrustDenied("peer route denied")
        now = self.clock()
        try:
            PolicyBuilder().store(Store(list(self.trust_roots))).time(now).max_chain_depth(
                4
            ).build_client_verifier().verify(cert, intermediates)
        except (VerificationError, ValueError) as error:
            raise TrustDenied("peer certificate not current/trusted") from error
        # Check expiry again after verification and just before the live fence.
        # Reusing a TLS channel never keeps an expired certificate admitted.
        now = self.clock()
        if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
            raise TrustDenied("peer certificate expired")
        state = self.fences.read()
        if not state.admits(peer) or (
            self.local_spiffe_id is not None and not state.admits(self.local_spiffe_id)
        ):
            raise TrustDenied("peer or destination workload fenced")
        if not cert.not_valid_before_utc <= self.clock() < cert.not_valid_after_utc:
            raise TrustDenied("peer certificate expired")
        return Admission(
            peer,
            state.generation,
            hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest(),
            cert.not_valid_after_utc,
        )
