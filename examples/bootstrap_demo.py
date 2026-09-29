"""在本地开发服务中创建 General Assistant 示例配置。"""

import os
import sys
from uuid import uuid4

import httpx


def main() -> None:
    api_url = os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")
    model_name = os.getenv("AGENT_MODEL_NAME")
    if not model_name:
        sys.exit("请设置 AGENT_MODEL_NAME")
    base_url = os.getenv("AGENT_MODEL_BASE_URL")
    provider = "openai-compatible" if base_url else "openai"
    suffix = uuid4().hex[:8]
    with httpx.Client(base_url=api_url, timeout=20) as client:
        model_response = client.post(
            "/api/models",
            json={
                "name": f"demo-model-{suffix}",
                "provider": provider,
                "model_name": model_name,
                "base_url": base_url,
                "api_key": os.getenv("AGENT_MODEL_API_KEY"),
            },
        )
        model_response.raise_for_status()
        model = model_response.json()
        tools_response = client.get("/api/tools")
        tools_response.raise_for_status()
        calculator = next(
            (item for item in tools_response.json() if item["name"] == "calculator"), None
        )
        if calculator is None:
            tool_response = client.post("/api/tools", json={"name": "calculator", "type": "NATIVE"})
            tool_response.raise_for_status()
            calculator = tool_response.json()
        agent_response = client.post(
            "/api/agents",
            json={
                "name": f"General Assistant {suffix}",
                "description": "V0.1 算术工具链路示例",
                "system_prompt": "请简洁回答；遇到算术问题时使用 calculator。",
                "model_id": model["id"],
                "tool_ids": [calculator["id"]],
            },
        )
        agent_response.raise_for_status()
        agent = agent_response.json()
        print(f"Agent ID: {agent['id']}")
        print(f"Model ID: {model['id']}")
        print(f"Tool ID: {calculator['id']}")


if __name__ == "__main__":
    main()
