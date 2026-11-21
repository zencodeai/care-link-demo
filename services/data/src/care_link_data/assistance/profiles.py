"""Closed first-slice profiles; unsupported projections stay disabled."""

from care_link_domain import ManualError

PROFILES = {"worker_summary": frozenset({"worker"})}
TOOLS = frozenset({"session_read"})
FIELDS = frozenset({"needs", "preferences", "observations", "rationale", "summary", "outcome"})
BUDGETS = {
    "max_steps": 4,
    "max_tools": 3,
    "max_proposal_attempts": 2,
    "context_tokens": 8192,
    "output_tokens": 1024,
}


def assert_profile(function: str, role: str) -> None:
    if role not in PROFILES.get(function, frozenset()):
        raise ManualError("assistance.function_disabled", 409)


def assert_goal(function: str, goal: str, completion: str) -> None:
    if function != "worker_summary" or goal != "prepare_summary" or completion != "draft_ready":
        raise ManualError("assistance.goal_unavailable", 409)
