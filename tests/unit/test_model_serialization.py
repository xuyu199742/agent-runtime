import json

from langchain_core.messages import AIMessage, HumanMessage

from app import execution


def test_model_serializer_keeps_only_safe_fields():
    assert hasattr(execution, "serialize_model_output")
    message = AIMessage(
        content="公开回答",
        tool_calls=[{"name": "calculator", "args": {"expression": "2+2"}, "id": "call-1"}],
        additional_kwargs={"reasoning_content": "隐藏推理", "Authorization": "secret-key"},
        response_metadata={"finish_reason": "tool_calls", "provider_raw": "private"},
        usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
    )

    result = execution.serialize_model_output(message)

    assert result == {
        "role": "assistant",
        "content": "公开回答",
        "tool_calls": [{"name": "calculator", "args": {"expression": "2+2"}, "id": "call-1"}],
        "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
        "finish_reason": "tool_calls",
    }
    persisted = json.dumps(result, ensure_ascii=False)
    assert "隐藏推理" not in persisted
    assert "secret-key" not in persisted
    assert "provider_raw" not in persisted


def test_model_input_serializer_excludes_additional_kwargs():
    assert hasattr(execution, "serialize_model_input")
    messages = [
        HumanMessage(content="问题", additional_kwargs={"api_key": "secret-key"}),
        AIMessage(content="答案", additional_kwargs={"reasoning_content": "隐藏推理"}),
    ]

    result = execution.serialize_model_input(messages)

    assert result == [
        {"role": "user", "content": "问题", "tool_calls": []},
        {"role": "assistant", "content": "答案", "tool_calls": []},
    ]
    assert "secret-key" not in json.dumps(result, ensure_ascii=False)
