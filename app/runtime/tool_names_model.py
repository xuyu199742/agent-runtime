"""在供应商请求边界映射工具名，Runtime 与持久事实保留内部规范名称。"""

import re
from copy import deepcopy
from hashlib import sha256

from langchain_openai import ChatOpenAI
from pydantic import PrivateAttr

_PREFIX = "rtx_"
_VALID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ToolNameChatOpenAI(ChatOpenAI):
    _tool_aliases: dict[str, str] = PrivateAttr(default_factory=dict)

    def _wire_name(self, name: str) -> str:
        if _VALID.fullmatch(name) and not name.startswith(_PREFIX):
            return name
        alias = _PREFIX + sha256(name.encode()).hexdigest()[:60]
        previous = self._tool_aliases.setdefault(alias, name)
        if previous != name:
            raise ValueError("供应商工具名称映射冲突")
        return alias

    def _canonical_name(self, name: str) -> str:
        if not name.startswith(_PREFIX):
            return name
        if name not in self._tool_aliases:
            if name in self._tool_aliases.values():
                return name
            raise ValueError("模型返回了未知工具名称映射")
        return self._tool_aliases[name]

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # 不原地修改 bind_tools 保存的共享 schema 或调用者提供的历史。
        for key in ("tools", "messages", "input", "tool_choice"):
            if key in payload:
                payload[key] = deepcopy(payload[key])
        for tool in payload.get("tools", []):
            function = tool.get("function", tool)
            if isinstance(function.get("name"), str):
                function["name"] = self._wire_name(function["name"])
        for message in payload.get("messages", []):
            if message.get("role") == "tool" and isinstance(message.get("name"), str):
                message["name"] = self._wire_name(message["name"])
            for call in message.get("tool_calls") or []:
                function = call.get("function", {})
                if isinstance(function.get("name"), str):
                    function["name"] = self._wire_name(function["name"])
        for item in payload.get("input", []):
            if item.get("type") == "function_call" and isinstance(item.get("name"), str):
                item["name"] = self._wire_name(item["name"])
        choice = payload.get("tool_choice")
        if isinstance(choice, dict):
            function = choice.get("function", choice)
            if isinstance(function.get("name"), str):
                function["name"] = self._wire_name(function["name"])
        return payload

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        chunk = deepcopy(chunk)
        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices", [])
        for choice in choices:
            for call in (choice.get("delta") or {}).get("tool_calls") or []:
                function = call.get("function") or {}
                if isinstance(function.get("name"), str) and function["name"]:
                    function["name"] = self._canonical_name(function["name"])
        return super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        for generation in result.generations:
            message = generation.message
            for call in [
                *getattr(message, "tool_calls", []),
                *getattr(message, "invalid_tool_calls", []),
            ]:
                if isinstance(call.get("name"), str):
                    call["name"] = self._canonical_name(call["name"])
            for call in message.additional_kwargs.get("tool_calls") or []:
                function = call.get("function") or {}
                if isinstance(function.get("name"), str):
                    function["name"] = self._canonical_name(function["name"])
        return result

    def _restore_message_names(self, message):
        # Responses API 绕过 Chat Completions 的解析钩子，在共同返回边界再还原一次。
        for attribute in ("tool_calls", "invalid_tool_calls", "tool_call_chunks"):
            for call in getattr(message, attribute, []) or []:
                if isinstance(call.get("name"), str) and call["name"]:
                    call["name"] = self._canonical_name(call["name"])
        if isinstance(message.content, list):
            for block in message.content:
                if (
                    isinstance(block, dict)
                    and block.get("type") in {"tool_call", "function_call"}
                    and isinstance(block.get("name"), str)
                ):
                    block["name"] = self._canonical_name(block["name"])
        return message

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        for generation in result.generations:
            self._restore_message_names(generation.message)
        return result

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        for generation in result.generations:
            self._restore_message_names(generation.message)
        return result

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for chunk in super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
            self._restore_message_names(chunk.message)
            yield chunk

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            self._restore_message_names(chunk.message)
            yield chunk
