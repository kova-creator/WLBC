import datetime as dt

import httpx
import pytest

from wlbc.oura import OuraAuthError, OuraClient, OuraForbiddenError, StaticTokenAuth
from wlbc.oura.errors import OuraRateLimitError


def client_with(handler, **kwargs):
    return OuraClient(
        auth=StaticTokenAuth("test-token"),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_sends_bearer_token():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"age": 33})

    with client_with(handler) as client:
        assert client.personal_info() == {"age": 33}
    assert seen["auth"] == "Bearer test-token"


def test_follows_next_token_across_pages():
    pages = {
        None: {"data": [{"id": "a"}], "next_token": "tok1"},
        "tok1": {"data": [{"id": "b"}], "next_token": None},
    }

    def handler(request):
        token = request.url.params.get("next_token")
        return httpx.Response(200, json=pages[token])

    with client_with(handler) as client:
        assert client.daily_sleep() == [{"id": "a"}, {"id": "b"}]


def test_date_params_are_serialized():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"data": [], "next_token": None})

    with client_with(handler) as client:
        client.daily_activity(dt.date(2026, 8, 1), dt.date(2026, 8, 6), fields=["score", "steps"])

    assert seen == {"start_date": "2026-08-01", "end_date": "2026-08-06", "fields": "score,steps"}


def test_sandbox_switches_path_prefix():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": [], "next_token": None})

    with client_with(handler, sandbox=True) as client:
        client.daily_readiness()

    assert seen["path"] == "/v2/sandbox/usercollection/daily_readiness"


def test_retries_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("wlbc.oura.client.time.sleep", lambda _: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json={"data": [{"id": "x"}], "next_token": None})

    with client_with(handler) as client:
        assert client.daily_stress() == [{"id": "x"}]
    assert calls["n"] == 2


def test_raises_after_retry_budget(monkeypatch):
    monkeypatch.setattr("wlbc.oura.client.time.sleep", lambda _: None)

    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "1", "X-RateLimit-Tier": "token"}, json={})

    with client_with(handler, max_retries=2) as client:
        with pytest.raises(OuraRateLimitError) as exc:
            client.daily_sleep()
    assert exc.value.tier == "token"


def test_401_without_refresh_raises_auth_error():
    def handler(request):
        return httpx.Response(401, json={})

    with client_with(handler) as client:
        with pytest.raises(OuraAuthError):
            client.personal_info()


def test_401_triggers_single_refresh():
    class RefreshingAuth:
        def __init__(self):
            self.token = "stale"
            self.refreshes = 0

        def access_token(self):
            return self.token

        def refresh(self):
            self.refreshes += 1
            self.token = "fresh"
            return True

    auth = RefreshingAuth()
    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer stale":
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"age": 30})

    with OuraClient(auth=auth, transport=httpx.MockTransport(handler)) as client:
        assert client.personal_info() == {"age": 30}

    assert auth.refreshes == 1
    assert seen == ["Bearer stale", "Bearer fresh"]


def test_403_is_distinct_from_401():
    def handler(request):
        return httpx.Response(403, json={"detail": "subscription expired"})

    with client_with(handler) as client:
        with pytest.raises(OuraForbiddenError):
            client.workout()


def test_rejects_wrong_collection_kind():
    with client_with(lambda r: httpx.Response(200, json={})) as client:
        with pytest.raises(ValueError):
            client.date_range("heartrate")
        with pytest.raises(ValueError):
            client.datetime_range("daily_sleep")
