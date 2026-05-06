"""WS ticket flow used by the Inkstone BFF.

The Next.js BFF holds STATE_BRIDGE_TOKEN and proxies HTTP/SSE traffic.
For WebSockets it instead requests a single-use 30-second ticket from
POST /auth/ws-ticket and returns it to the browser, which uses it as
?token=<ticket> on the WS upgrade.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import app as bridge_app  # noqa: F401  (imported for module side effects in conftest)


def test_ws_ticket_requires_bearer(bridge_testbed):
    app_module, _, _, _ = bridge_testbed
    # Fresh TestClient with no default auth header.
    with TestClient(app_module.app) as anon_client:
        response = anon_client.post("/auth/ws-ticket")
        assert response.status_code == 401


def test_ws_ticket_payload_shape(client):
    response = client.post("/auth/ws-ticket")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("ticket"), str)
    assert len(body["ticket"]) >= 32
    assert body.get("expires_in") == 30


def test_ws_ticket_validates_via_check_token(client, bridge_testbed):
    app_module, _, _, _ = bridge_testbed
    response = client.post("/auth/ws-ticket")
    ticket = response.json()["ticket"]

    # Ticket validates as if it were the bearer (single use).
    assert app_module._check_token(ticket, allow_ticket=True) is True
    # ...and is consumed afterwards.
    assert app_module._check_token(ticket, allow_ticket=True) is False


def test_tickets_do_not_validate_outside_ws_path(client, bridge_testbed):
    """HTTP/SSE callers must use the long-lived bearer, not a ticket."""
    app_module, _, _, _ = bridge_testbed
    response = client.post("/auth/ws-ticket")
    ticket = response.json()["ticket"]

    # allow_ticket defaults to False on HTTP — the bearer middleware
    # uses _check_token without the kwarg.
    assert app_module._check_token(ticket) is False


def test_ticket_count_capped(bridge_testbed):
    app_module, _, _, _ = bridge_testbed
    # Drain any tickets from earlier tests.
    app_module._ws_tickets.clear()

    issued = []
    for _ in range(app_module.WS_TICKET_MAX_LIVE + 32):
        ticket, _ttl = app_module._issue_ws_ticket()
        issued.append(ticket)
    assert len(app_module._ws_tickets) <= app_module.WS_TICKET_MAX_LIVE
