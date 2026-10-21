import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from app.domain.agent import ModelDefinition
from app.runtime.factory import ModelRuntimeConfig, build_model


def model(provider="openai-compatible"):
    return build_model(
        ModelRuntimeConfig(
            ModelDefinition(provider=provider, model_name="test", base_url="https://example.com"),
            credential="test-key",
        )
    )


def schema(name):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "read",
            "parameters": {"type": "object", "properties": {}},
        },
    }


@pytest.mark.parametrize("provider", ["openai", "openai-compatible"])
def test_invalid_tool_name_is_aliased_on_wire_and_restored_before_routing(provider):
    chat = model(provider)
    tools = [schema("skill.read"), schema("calculator"), schema("rtx_reserved")]
    historical = AIMessage(content="", tool_calls=[{"id": "c1", "name": "skill.read", "args": {}}])
    payload = chat._get_request_payload(
        [HumanMessage(content="read"), historical],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "skill.read"}},
    )
    alias = payload["tools"][0]["function"]["name"]
    assert alias != "skill.read" and len(alias) <= 64 and "." not in alias
    assert payload["tools"][1]["function"]["name"] == "calculator"
    assert payload["tools"][2]["function"]["name"] != "rtx_reserved"
    assert tools[0]["function"]["name"] == "skill.read"
    assert payload["messages"][1]["tool_calls"][0]["function"]["name"] == alias
    assert payload["tool_choice"]["function"]["name"] == alias
    first = chat._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c2",
                                "type": "function",
                                "function": {"name": alias, "arguments": ""},
                            }
                        ],
                    }
                }
            ]
        },
        AIMessageChunk,
        None,
    )
    second = chat._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]}}]},
        AIMessageChunk,
        None,
    )
    assert (first.message + second.message).tool_calls[0]["name"] == "skill.read"
    result = chat._create_chat_result(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c3",
                                "type": "function",
                                "function": {"name": alias, "arguments": "{}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )
    assert result.generations[0].message.tool_calls[0]["name"] == "skill.read"
    restored = model(provider)
    again = restored._get_request_payload([HumanMessage(content="resume")], tools=tools)
    assert again["tools"][0]["function"]["name"] == alias


def test_stream_accepts_null_tool_calls_from_compatible_provider():
    chat = model()
    chunk = chat._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "先检查",
                        "tool_calls": None,
                    }
                }
            ]
        },
        AIMessageChunk,
        None,
    )
    assert chunk.message.additional_kwargs["reasoning_content"] == "先检查"


async def test_responses_api_result_and_stream_restore_alias_at_common_boundary(monkeypatch):
    from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
    from langchain_openai import ChatOpenAI

    chat = model("openai")
    alias = chat._get_request_payload([HumanMessage(content="read")], tools=[schema("skill.read")])[
        "tools"
    ][0]["function"]["name"]

    async def responses_result(self, *args, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=[
                            {"type": "tool_call", "name": alias, "id": "c1", "args": {}},
                        ],
                        tool_calls=[{"name": alias, "id": "c1", "args": {}}],
                    )
                )
            ]
        )

    async def responses_stream(self, *args, **kwargs):
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"name": alias, "id": "c1", "args": "{}", "index": 0},
                ],
            )
        )

    monkeypatch.setattr(ChatOpenAI, "_agenerate", responses_result)
    monkeypatch.setattr(ChatOpenAI, "_astream", responses_stream)
    result = await chat._agenerate([HumanMessage(content="read")])
    assert result.generations[0].message.tool_calls[0]["name"] == "skill.read"
    assert result.generations[0].message.content[0]["name"] == "skill.read"
    async for chunk in chat._astream([HumanMessage(content="read")]):
        assert chunk.message.tool_call_chunks[0]["name"] == "skill.read"
