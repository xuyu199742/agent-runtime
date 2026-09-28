"""仅供本地端到端测试的 OpenAI Chat Completions 流式桩。"""

import asyncio
import json
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


def chunk(delta: dict, finish_reason=None) -> str:
    payload = {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "stub-model",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/v1/chat/completions")
async def completion(request: Request):
    body = await request.json()
    has_tool_result = any(message.get("role") == "tool" for message in body["messages"])

    async def generate():
        if any("slow" in str(message.get("content", "")) for message in body["messages"]):
            await asyncio.sleep(2)
        if has_tool_result:
            yield chunk({"role": "assistant", "content": "答案是 4"})
            yield chunk({}, "stop")
        else:
            yield chunk(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-stub",
                            "type": "function",
                            "function": {"name": "calculator", "arguments": '{"expression":"2+2"}'},
                        }
                    ],
                }
            )
            yield chunk({}, "tool_calls")
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
