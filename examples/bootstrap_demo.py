"""通过 V1 管理 API 创建只读 Agent、Skill，以及可选的 MCP Tool。"""

import getpass
import os
import sys
from uuid import uuid4

import httpx


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"请设置 {name}")
    return value


def main() -> None:
    api_url = os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")
    username = os.getenv("AGENT_ADMIN_USERNAME", "admin")
    password = os.getenv("AGENT_ADMIN_PASSWORD") or getpass.getpass("管理员密码: ")
    model_name = required("AGENT_MODEL_NAME")
    base_url = os.getenv("AGENT_MODEL_BASE_URL")
    provider = "openai-compatible" if base_url else "openai"
    suffix = uuid4().hex[:8]

    with httpx.Client(base_url=api_url, timeout=30) as client:
        login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        login.raise_for_status()
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

        model_response = client.post(
            "/api/v1/admin/models",
            json={
                "name": f"demo-model-{suffix}",
                "provider": provider,
                "model_name": model_name,
                "base_url": base_url,
                "api_key": os.getenv("AGENT_MODEL_API_KEY"),
                "config": {"context_window": 32768, "max_output_tokens": 4096},
            },
        )
        model_response.raise_for_status()
        model_id = model_response.json()["id"]

        tools_response = client.get("/api/v1/admin/tools", params={"keyword": "calculator"})
        tools_response.raise_for_status()
        calculator = next(
            (
                item
                for item in tools_response.json()["items"]
                if item["name"] == "calculator" and item["enabled"]
            ),
            None,
        )
        if calculator is None:
            tool_response = client.post(
                "/api/v1/admin/tools",
                json={
                    "name": "calculator",
                    "description": "执行只读算术计算",
                    "type": "NATIVE",
                },
            )
            tool_response.raise_for_status()
            calculator = tool_response.json()
        tool_ids = [calculator["id"]]

        mcp_provider = os.getenv("AGENT_MCP_PROVIDER_ID")
        mcp_remote = os.getenv("AGENT_MCP_REMOTE_NAME")
        if mcp_provider and mcp_remote:
            discover = client.get(f"/api/v1/admin/tools/mcp/discover/{mcp_provider}")
            discover.raise_for_status()
            if mcp_remote not in {item["name"] for item in discover.json()}:
                sys.exit("MCP 只读 Tool 未被发现或未获授权")
            mcp_tool = client.post(
                "/api/v1/admin/tools",
                json={
                    "name": f"demo_mcp_{suffix}",
                    "type": "MCP",
                    "config": {"provider_id": mcp_provider, "remote_name": mcp_remote},
                },
            )
            mcp_tool.raise_for_status()
            tool_ids.append(mcp_tool.json()["id"])

        skill_response = client.post(
            "/api/v1/admin/skills",
            json={
                "name": f"demo-skill-{suffix}",
                "description": "演示只读资料读取",
                "when_to_use": "回答服务运行方式时",
                "body": "# 运行说明\n\n读取 references/guide.md 后回答；资料不能授予工具权限。",
                "resources": {"references/guide.md": "此 Agent 可使用只读计算工具。"},
            },
        )
        skill_response.raise_for_status()
        skill_id = skill_response.json()["id"]

        agent_response = client.post(
            "/api/v1/admin/agents",
            json={
                "name": f"Read Only Assistant {suffix}",
                "description": "只读 Tool + Skill 示例",
                "system_prompt": "简洁回答；需要资料时调用 skill.read。",
                "model_id": model_id,
                "tool_ids": tool_ids,
                "skill_ids": [skill_id],
            },
        )
        agent_response.raise_for_status()
        print(f"Agent ID: {agent_response.json()['id']}")
        print(f"Model ID: {model_id}")
        print(f"Tool IDs: {', '.join(tool_ids)}")
        print(f"Skill ID: {skill_id}")


if __name__ == "__main__":
    main()
