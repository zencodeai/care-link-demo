"""HTTP status taxonomy and categorical diagnostics over the real adapters."""

import httpx
import pytest
from care_link_help import HelpError, HttpAuthority, HttpBrowserSessions

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("status", [401, 403, 400, 404, 422, 500, 503])
def test_authority_policy_denials_remain_denials_and_other_failures_unavailable(status, caplog):
    def response(request):
        assert request.extensions["timeout"] == {
            "connect": 1,
            "read": 1,
            "write": 1,
            "pool": 1,
        }
        return httpx.Response(status, json={"error_key": "private-upstream-never-log"})

    client = httpx.Client(transport=httpx.MockTransport(response))
    authority = HttpAuthority(client, "https://identity-private-never-log.test")
    with pytest.raises(HelpError) as caught:
        authority.authorize({"private-request-never-log": "private-value-never-log"})
    assert caught.value.status == (403 if status in {401, 403} else 503)
    assert caught.value.code == (
        "help.authority_denied" if status in {401, 403} else "help.identity_unavailable"
    )
    records = [record for record in caplog.records if record.name.endswith(".authority")]
    assert len(records) == 1
    assert (
        records[0].getMessage() == f"Identity HTTP adapter failed: stage=authorize status={status}"
    )
    assert records[0].exc_info is None
    assert "never-log" not in caplog.text


@pytest.mark.parametrize("operation", ["context", "proof"])
@pytest.mark.parametrize("status", [401, 403, 500])
def test_browser_context_and_proof_preserve_invalid_session_status(operation, status, caplog):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status, json={"error_key": "private-never-log"})
        )
    )
    sessions = HttpBrowserSessions(client, "https://identity.test", "https://help.test")
    with pytest.raises(HelpError) as caught:
        if operation == "context":
            sessions.context("private-cookie-never-log")
        else:
            sessions.proof("private-cookie-never-log", "https://help.test")
    assert caught.value.status == (status if status in {401, 403} else 503)
    expected_stage = "browser_context" if operation == "context" else "browser_proof"
    assert f"stage={expected_stage} status={status}" in caplog.text
    assert "never-log" not in caplog.text


@pytest.mark.parametrize("operation", ["authorize", "context", "proof"])
def test_transport_failure_remains_unavailable_without_logging_http_exception(operation, caplog):
    def timeout(request):
        raise httpx.ReadTimeout("private-exception-never-log", request=request)

    client = httpx.Client(transport=httpx.MockTransport(timeout))
    sessions = HttpBrowserSessions(client, "https://identity.test", "https://help.test")
    with pytest.raises(HelpError) as caught:
        if operation == "authorize":
            sessions.authority.authorize({})
        elif operation == "context":
            sessions.context("private-cookie-never-log")
        else:
            sessions.proof("private-cookie-never-log", "https://help.test")
    assert caught.value.status == 503
    assert "status=None" in caplog.text and "never-log" not in caplog.text


@pytest.mark.parametrize("operation", ["context", "proof"])
def test_invalid_success_payload_is_unavailable_and_logs_only_schema_stage(operation, caplog):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"private-never-log": "private-never-log"})
        )
    )
    sessions = HttpBrowserSessions(client, "https://identity.test", "https://help.test")
    with pytest.raises(HelpError) as caught:
        if operation == "context":
            sessions.context("private-cookie-never-log")
        else:
            sessions.proof("private-cookie-never-log", "https://help.test")
    assert caught.value.status == 503
    assert "_schema status=200" in caplog.text and "never-log" not in caplog.text
