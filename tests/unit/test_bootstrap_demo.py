import httpx

from examples import bootstrap_demo


def test_bootstrap_demo_uses_v1_admin_api_and_discovered_mcp(monkeypatch, capsys):
    calls = []

    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "test-token"})
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.url.path == "/api/v1/admin/models":
            return httpx.Response(201, json={"id": "model-1"})
        if request.url.path == "/api/v1/admin/tools" and request.method == "GET":
            return httpx.Response(200, json={"items": []})
        if request.url.path == "/api/v1/admin/tools/mcp/discover/search":
            return httpx.Response(200, json=[{"name": "lookup"}])
        if request.url.path == "/api/v1/admin/tools" and request.method == "POST":
            return httpx.Response(
                201,
                json={"id": "mcp-1" if b'"MCP"' in request.content else "calculator-1"},
            )
        if request.url.path == "/api/v1/admin/skills":
            return httpx.Response(201, json={"id": "skill-1"})
        if request.url.path == "/api/v1/admin/agents":
            assert b'"skill-1"' in request.content
            assert b'"mcp-1"' in request.content
            return httpx.Response(201, json={"id": "agent-1"})
        raise AssertionError(request.url.path)

    original_client = httpx.Client
    monkeypatch.setattr(
        bootstrap_demo.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.setenv("AGENT_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("AGENT_MODEL_NAME", "test-model")
    monkeypatch.setenv("AGENT_MCP_PROVIDER_ID", "search")
    monkeypatch.setenv("AGENT_MCP_REMOTE_NAME", "lookup")
    bootstrap_demo.main()
    assert ("POST", "/api/v1/admin/agents") in calls
    assert "Agent ID: agent-1" in capsys.readouterr().out
