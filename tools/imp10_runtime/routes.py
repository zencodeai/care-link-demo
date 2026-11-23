"""Exact protected IMP-10 transport paths shared by the application and mesh."""

TRAINING_ACTIONS = ("scenario_create", "scenario_read", "scenario_stop")
EVALUATION_ACTIONS = ("replay_create", "evaluation_read")

TRAINING_ROUTES = frozenset(
    ("POST", "/internal/v1/training/" + action) for action in TRAINING_ACTIONS
)
EVALUATION_ROUTES = frozenset(
    ("POST", "/internal/v1/data/" + action) for action in EVALUATION_ACTIONS
)
TRAINING_IDENTITY_ROUTES = frozenset(
    ("POST", "/internal/v1/manual-identity/" + action) for action in ("resolve", "current")
)
HELP_IDENTITY_ROUTES = frozenset(
    ("POST", "/internal/v1/identity/" + action)
    for action in ("help-authorize", "help-browser-context", "help-browser-proof")
)
HELP_AUTH_ROUTES = frozenset(
    (method, "/bff/help/v1/auth/" + path)
    for method, path in (
        ("GET", "csrf"),
        ("POST", "login"),
        ("GET", "callback"),
        ("GET", "session"),
        ("POST", "logout"),
        ("POST", "step-up"),
        ("POST", "step-up/confirm"),
        ("GET", "step-up/proof"),
    )
)
