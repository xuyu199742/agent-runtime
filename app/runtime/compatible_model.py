"""补足 OpenAI-compatible 的公开推理字段，不透传任意供应商元数据。"""

from langchain_core.messages import AIMessage

from app.runtime.errors import ReasoningContextMissing
from app.runtime.tool_names_model import ToolNameChatOpenAI


class CompatibleChatOpenAI(ToolNameChatOpenAI):
    """保留 reasoning_content，以支持展示和工具调用后的模型续调。"""

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        result = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices", [])
        if result is not None and choices and isinstance(result.message, AIMessage):
            reasoning = (choices[0].get("delta") or {}).get("reasoning_content")
            if isinstance(reasoning, str):
                result.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        source = response if isinstance(response, dict) else response.model_dump(warnings=False)
        for generation, choice in zip(result.generations, source.get("choices", [])):
            reasoning = choice.get("message", {}).get("reasoning_content")
            if isinstance(reasoning, str) and isinstance(generation.message, AIMessage):
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        # 先规范化一次输入，保持 LangChain 对工具消息、系统消息的既有转换。
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        if payload.get("tools") and "messages" in payload:
            for message, item in zip(messages, payload["messages"]):
                if isinstance(message, AIMessage) and item.get("role") == "assistant":
                    reasoning = message.additional_kwargs.get("reasoning_content")
                    if isinstance(reasoning, str):
                        item["reasoning_content"] = reasoning
                    elif (
                        message.tool_calls
                        and self.model_name.startswith("deepseek-")
                        and self.reasoning_effort != "none"
                        and (self.extra_body or {}).get("thinking", {}).get("type") != "disabled"
                    ):
                        raise ReasoningContextMissing(
                            "旧工具检查点缺少 reasoning_content，无法安全恢复推理续调；请重新发起任务"
                        )
        return payload
