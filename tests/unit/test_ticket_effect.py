from types import SimpleNamespace

import httpx
import pytest

from app.execution.config import resolve_execution_config
from app.runtime.effects.contract import ObservationStatus
from app.runtime.effects.ticket import TicketCreateProvider
from app.worker.runner import build_effect_providers


def _spec(version, tools):
    return SimpleNamespace(
        schema_version=version,
        snapshot={
            "prompt": {"rendered": ""},
            "max_model_calls": 3,
            "tools": tools,
            "context_policy": {},
            "context_budget": {},
            "model": {"provider": "openai", "model_name": "fake"},
        },
    )


def _write_tool():
    return {
        "name": "ticket.create",
        "type": "NATIVE",
        "effect_type": "EXTERNAL_WRITE",
        "policy": {"write_allowed": True},
        "config": {
            "effect_contract": {
                "operation_name": "ticket.create",
                "provider_namespace": "account-a",
                "contract_version": 1,
            }
        },
    }


def test_worker_requires_schema_3_and_frozen_contract():
    settings = SimpleNamespace(
        ticket_service_base_url="https://tickets.example", ticket_service_token="x"
    )
    old = resolve_execution_config(_spec(2, [_write_tool()]), None, None, None)
    with pytest.raises(ValueError, match="未冻结"):
        build_effect_providers(old, settings)
    current = resolve_execution_config(_spec(3, [_write_tool()]), None, None, None)
    assert build_effect_providers(current, settings)["ticket.create"].namespace == "account-a"
    broken = _write_tool()
    broken["config"]["effect_contract"]["provider_namespace"] = ""
    with pytest.raises(ValueError, match="Contract"):
        resolve_execution_config(_spec(3, [broken]), None, None, None)


async def test_ticket_provider_hashes_normalized_request_and_404_is_unknown():
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"ticket_id": "T-1"})
        return httpx.Response(404)

    provider = TicketCreateProvider(
        "account-a", "https://tickets.example", "secret", transport=httpx.MockTransport(respond)
    )
    first = provider.identity({"ticket_key": " warning-100 ", "title": " Engine warning "})
    second = provider.identity({"ticket_key": "warning-100", "title": "Engine warning"})
    assert first == second
    assert first.business_key == "ticket:create:warning-100"
    assert (
        provider.identity({"ticket_key": "warning-100", "title": "Other"}).request_hash
        != first.request_hash
    )
    created = await provider.invoke(
        {"ticket_key": "warning-100", "title": "Engine warning"}, first.business_key
    )
    assert created.status == ObservationStatus.SUCCEEDED
    assert requests[0].headers["Idempotency-Key"] == first.business_key
    assert (await provider.reconcile(first)).status == ObservationStatus.UNKNOWN


def test_ticket_provider_rejects_non_https_and_unstable_args():
    with pytest.raises(ValueError, match="HTTPS"):
        TicketCreateProvider("account-a", "http://tickets.example", "secret")
    provider = TicketCreateProvider("account-a", "https://tickets.example", "secret")
    with pytest.raises(ValueError, match="ticket_key"):
        provider.identity({"ticket_key": "", "title": "title"})
