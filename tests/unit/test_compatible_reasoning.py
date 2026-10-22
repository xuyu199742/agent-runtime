import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.domain.agent import ModelDefinition
from app.runtime.factory import ModelRuntimeConfig, build_model
from app.transport.schemas.legacy import ModelIn


def model(**config):
    return build_model(
        ModelRuntimeConfig(
            ModelDefinition(
                provider="openai-compatible",
                model_name="deepseek-flash",
                base_url="https://api.deepseek.com",
                config=config,
            )
        )
    )


def test_compatible_reasoning_stream_and_tool_continuation():
    chat = model(thinking_mode="enabled", reasoning_effort="low")
    chunk = chat._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"role": "assistant", "reasoning_content": "先计算"}}]},
        AIMessageChunk,
        None,
    )
    assert chunk.message.additional_kwargs["reasoning_content"] == "先计算"
    messages = [
        HumanMessage(content="计算"),
        AIMessage(
            content="",
            additional_kwargs={
                "reasoning_content": "先计算",
                "private_metadata": "不发送",
            },
            tool_calls=[{"id": "c1", "name": "calculator", "args": {"expression": "1+1"}}],
        ),
        ToolMessage(content="2", tool_call_id="c1"),
    ]
    payload = chat._get_request_payload(messages, tools=[{"type": "function"}])
    assert payload["messages"][1]["reasoning_content"] == "先计算"
    assert "private_metadata" not in str(payload)
    assert payload["extra_body"] == {"thinking": {"type": "enabled"}}
    assert payload["reasoning_effort"] == "low"


def test_compatible_nonstream_result_preserves_only_reasoning_extension():
    result = model()._create_chat_result(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "2",
                        "reasoning_content": "计算完成",
                        "api_key": "不要保留",
                    },
                    "finish_reason": "stop",
                }
            ]
        }
    )
    assert result.generations[0].message.additional_kwargs == {"reasoning_content": "计算完成"}


def test_openai_does_not_send_compatible_thinking_toggle():
    chat = build_model(
        ModelRuntimeConfig(
            ModelDefinition(
                provider="openai",
                model_name="gpt-test",
                config={"reasoning_effort": "low"},
            ),
            credential="test-key",
        )
    )
    payload = chat._get_request_payload([HumanMessage(content="hi")])
    assert "extra_body" not in payload
    assert payload["reasoning_effort"] == "low"


@pytest.mark.parametrize(
    "config",
    [
        {"thinking_mode": "maybe"},
        {"thinking_mode": True},
        {"reasoning_effort": 12},
        {"reasoning_effort": "unknown"},
        {"thinking_mode": "enabled", "reasoning_effort": "none"},
    ],
)
def test_model_rejects_invalid_reasoning_config(config):
    with pytest.raises(ValueError):
        ModelIn(
            name="test",
            provider="openai-compatible",
            model_name="deepseek-flash",
            base_url="https://api.deepseek.com",
            config={
                "context_window": 8192,
                "max_output_tokens": 1024,
                **config,
            },
        )


def test_model_accepts_explicit_reasoning_config():
    body = ModelIn(
        name="test",
        provider="openai-compatible",
        model_name="deepseek-flash",
        base_url="https://api.deepseek.com",
        config={
            "context_window": 8192,
            "max_output_tokens": 1024,
            "thinking_mode": "enabled",
            "reasoning_effort": "low",
        },
    )
    assert body.config["thinking_mode"] == "enabled"


def test_working_context_counts_reasoning_returned_to_tool_model():
    from app.context.working import plan_working_context
    from app.runtime.working_context import _working_messages

    messages = [
        HumanMessage(content="计算", id="u1"),
        AIMessage(
            content="",
            id="a1",
            additional_kwargs={"reasoning_content": "很长的推理" * 100},
            tool_calls=[{"id": "c1", "name": "calculator", "args": {"expression": "1+1"}}],
        ),
        ToolMessage(content="2", tool_call_id="c1", id="t1"),
    ]
    plan = plan_working_context(_working_messages(messages), soft_limit=100, hard_limit=200)
    assert plan.action == "FAIL"


async def test_working_context_accepts_standard_reasoning_blocks_without_flattening():
    from app.runtime.working_context import WorkingContextMiddleware, _working_messages

    message = AIMessage(
        id="a1",
        content=[
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "验证计算"}]},
            {"type": "text", "text": "2"},
        ],
    )

    async def refs():
        return {}

    middleware = WorkingContextMiddleware(
        model=None,
        journal=None,
        soft_limit=100,
        hard_limit=200,
        summary_input_budget=100,
        max_compaction_rounds=2,
        fact_refs_loader=refs,
    )
    assert _working_messages([message])[0].reasoning_tokens > 0
    assert await middleware.abefore_model({"messages": [message]}, None) is None
    assert isinstance(message.content, list)


def test_old_deepseek_tool_checkpoint_fails_explicitly_without_fabricating_reasoning():
    message = AIMessage(
        content="",
        tool_calls=[
            {"id": "old", "name": "calculator", "args": {"expression": "1+1"}},
        ],
    )
    from app.runtime.errors import ReasoningContextMissing

    with pytest.raises(ReasoningContextMissing, match="旧工具检查点缺少 reasoning_content"):
        model()._get_request_payload([message], tools=[{"type": "function"}])
    assert "reasoning_content" not in message.additional_kwargs
    payload = model(thinking_mode="disabled")._get_request_payload(
        [message], tools=[{"type": "function"}]
    )
    assert "reasoning_content" not in payload["messages"][0]


def test_deepseek_none_effort_allows_tool_continuation_without_reasoning():
    message = AIMessage(
        content="",
        tool_calls=[
            {"id": "c1", "name": "calculator", "args": {"expression": "1+1"}},
        ],
    )
    payload = model(reasoning_effort="none")._get_request_payload(
        [message], tools=[{"type": "function"}]
    )
    assert "reasoning_content" not in payload["messages"][0]
