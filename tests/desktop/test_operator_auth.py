import httpx
import pytest
from desktop.api.client import SentinelOpsClient
from desktop.api.exceptions import SentinelOpsApiError


def test_hosted_operator_header():
    seen = []
    def handler(request):
        seen.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"status": "ok"})
    client = SentinelOpsClient("https://sentinel.example", operator_token="private",
                               transport=httpx.MockTransport(handler))
    client._request("GET", "/health")
    client.close()
    assert seen == ["Bearer private"]


def test_operator_auth_failure_is_useful_and_redacted():
    client = SentinelOpsClient(operator_token="private", transport=httpx.MockTransport(
        lambda request: httpx.Response(401, json={"detail": "private"})))
    with pytest.raises(SentinelOpsApiError, match="SENTINELOPS_OPERATOR_TOKEN") as caught:
        client._request("GET", "/projects")
    assert "private" not in str(caught.value)
    client.close()


def test_no_token_on_public_cleartext():
    with pytest.raises(ValueError, match="HTTPS"):
        SentinelOpsClient("http://example.com", operator_token="private")
