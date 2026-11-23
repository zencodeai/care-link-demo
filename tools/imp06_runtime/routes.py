"""Fixed workload graph for separately provisioned IMP-06 role processes."""

from care_link_domain import INFERENCE_ACTOR_PATH
from care_link_workload_trust import PeerRule

from tools.imp03_runtime.config import DATA_ACTIONS
from tools.imp03_runtime.config import routes as manual_routes
from tools.imp10_runtime.routes import EVALUATION_ROUTES, TRAINING_ROUTES

RUNTIME_ROUTES = frozenset(
    {
        ("POST", "/internal/v1/tasks/{task_id}/lease"),
        ("POST", "/internal/v1/tasks/{task_id}/renew"),
        ("POST", "/internal/v1/broker/work"),
        ("POST", "/internal/v1/broker/inference"),
        ("POST", "/internal/v1/broker/proposals"),
        ("POST", "/internal/v1/broker/tools"),
    }
)
INFERENCE_ROUTES = frozenset({("POST", "/internal/v1/inference/jobs")})
BRIDGE_ROUTES = frozenset(
    {
        ("POST", "/internal/v1/inference/execute"),
        ("POST", "/internal/v1/inference/tokenize"),
    }
)
LEDGER_ROUTES = frozenset(
    ("POST", "/internal/v1/data/assistance/inference/" + operation)
    for operation in ("context", "current", "reserve", "unknown", "complete")
)
TASK_ROUTES = frozenset(
    {
        ("POST", "/internal/v1/data/assistance/step_lease/{task_id}"),
        ("POST", "/internal/v1/data/assistance/step_renew/{task_id}"),
        *[
            ("POST", "/internal/v1/data/assistance/" + operation)
            for operation in ("tool_invoke", "reserve_proposal", "proposal_submit")
        ],
    }
)
ACTOR_ACTIONS = (
    "task_create",
    "task_read",
    "task_cancel",
    "task_revise",
    "draft_read",
    "draft_review",
    "assistance_task_context",
    "assistance_draft_context",
    "referral_draft",
    "referral_read",
    "referral_context",
    "referral_sources",
    "referral_review",
    "referral_dispatch",
    "dispatch_read",
    "receipt_read",
    "dispatcher_send",
    "dispatch_reconcile",
)
DATA_CORE_ROUTES = (
    frozenset(("POST", "/internal/v1/data/" + action) for action in (*DATA_ACTIONS, *ACTOR_ACTIONS))
    | TASK_ROUTES
)


def inbound(role: str, *, training_enabled: bool = False) -> tuple[PeerRule, ...]:
    if role == "core":
        return (
            PeerRule("spiffe://care-link.demo/demo/runtime", RUNTIME_ROUTES),
            PeerRule(
                "spiffe://care-link.demo/demo/data",
                manual_routes("core")["data"] | {("POST", INFERENCE_ACTOR_PATH)},
            ),
        )
    if role == "data":
        return (
            PeerRule(
                "spiffe://care-link.demo/demo/core",
                DATA_CORE_ROUTES | EVALUATION_ROUTES if training_enabled else DATA_CORE_ROUTES,
            ),
            PeerRule("spiffe://care-link.demo/demo/inference", LEDGER_ROUTES),
        )
    if role == "inference":
        return (PeerRule("spiffe://care-link.demo/demo/core", INFERENCE_ROUTES),)
    if role == "host-inference-bridge":
        return (PeerRule("spiffe://care-link.demo/demo/inference", BRIDGE_ROUTES),)
    raise ValueError("No IMP-06 inbound listener for this role")


def outbound(role: str, *, training_enabled: bool = False) -> dict[str, frozenset[tuple[str, str]]]:
    if role == "runtime":
        return {"core": RUNTIME_ROUTES}
    if role == "inference":
        return {"data": LEDGER_ROUTES, "host-inference-bridge": BRIDGE_ROUTES}
    if role == "core":
        result = {
            "data": DATA_CORE_ROUTES | EVALUATION_ROUTES if training_enabled else DATA_CORE_ROUTES,
            "inference": INFERENCE_ROUTES,
        }
        if training_enabled:
            result["training"] = TRAINING_ROUTES
        return result
    raise ValueError("Use existing manual ports or fixed host loopback adapter for this role")
