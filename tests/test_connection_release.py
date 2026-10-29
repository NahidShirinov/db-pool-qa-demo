"""The property under test: while the external API is answering, no database connection is checked out.

The fake external API records engine.pool.checkedout() at the moment the request arrives.
That is exactly the time the real API would spend thinking, so any held connection shows up here.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

import app as demo


@pytest.fixture
def held(monkeypatch):
    seen: list[int] = []

    def external_api(request: httpx.Request) -> httpx.Response:
        seen.append(demo.engine.pool.checkedout())
        return httpx.Response(200, json={"status": "paid"})

    monkeypatch.setattr(demo, "transport", httpx.MockTransport(external_api))
    return seen


@pytest.fixture
def order_id():
    with TestClient(demo.app) as client:
        return client.post("/orders").json()["id"]


def test_fixed_endpoint_releases_the_connection_during_the_external_call(held, order_id):
    with TestClient(demo.app) as client:
        res = client.post(f"/orders/{order_id}/pay")
    assert res.status_code == 200 and res.json()["status"] == "paid"
    assert held == [0]


def test_external_api_error_is_not_leaked(monkeypatch, order_id):
    monkeypatch.setattr(demo, "transport", httpx.MockTransport(lambda r: httpx.Response(500, text="internal trace")))
    with TestClient(demo.app) as client:
        res = client.post(f"/orders/{order_id}/pay")
    assert res.status_code == 502 and "internal trace" not in res.text


def test_buggy_endpoint_is_caught(held, order_id):
    """Proves the check can fail: if this test ever fails with held == [0], the measurement is broken, not the app fixed."""
    with TestClient(demo.app) as client:
        res = client.post(f"/orders/{order_id}/pay-buggy")
    assert res.status_code == 200
    assert held == [1]
