"""Only fixed safe downstream failure keys cross the human BFF boundary."""

from uuid import uuid4

import httpx
import pytest
from care_link_core.manual_http import HttpManualGateway
from care_link_domain import ManualError

from services.core.tests.test_manual_envelopes import fixture


@pytest.mark.parametrize(
    "status,code,supplied,expected",
    [
        (503, "DEPENDENCY_UNAVAILABLE", "manual.deadline", "manual.deadline"),
        (503, "DEPENDENCY_UNAVAILABLE", "manual.deadline_exceeded", "manual.deadline_exceeded"),
        (409, "INVALID_REQUEST", "manual.stale_authority", "manual.stale_authority"),
        (503, "DEPENDENCY_UNAVAILABLE", "manual.journal_barrier", "manual.journal_barrier"),
        (503, "DEPENDENCY_UNAVAILABLE", "manual.arbitrary_upstream", "manual.gateway_denied"),
        (403, "NOT_AUTHORIZED", "manual.deadline", "manual.gateway_denied"),
        (503, "DEPENDENCY_UNAVAILABLE", "manual.stale_authority", "manual.gateway_denied"),
        (503, "COMMIT_UNKNOWN", "manual.deadline", "manual.commit_unknown"),
        (409, "REVISION_CONFLICT", "manual.stale_authority", "manual.stale_revision"),
    ],
)
def test_known_gateway_errors_preserve_status_without_reflecting_unknown_keys(
    status, code, supplied, expected
):
    factory, actor, *_rest = fixture()

    def failure(_request):
        return httpx.Response(
            status,
            json={
                "code": code,
                "request_id": str(uuid4()),
                "retryable": status >= 500,
                "message_key": supplied,
                "operation_id": None,
                "retry_after_ms": None,
            },
        )

    gateway = HttpManualGateway(
        httpx.Client(transport=httpx.MockTransport(failure)), "https://data.test", factory
    )
    with pytest.raises(ManualError) as observed:
        gateway.session_read(actor, str(uuid4()))
    assert observed.value.code == expected
    assert observed.value.status == status
