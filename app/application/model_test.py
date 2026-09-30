"""通过真实最小推理测试模型，返回脱敏阶段结果。"""

import asyncio
from dataclasses import replace
from time import perf_counter

import openai

from app.domain.agent import ModelDefinition
from app.infrastructure.model_secrets import ModelSecretConfigurationError
from app.runtime.factory import ModelRuntimeConfig, build_model, resolve_model_config


def definition_from_record(record) -> ModelDefinition:
    return ModelDefinition(
        provider=record.provider,
        model_name=record.model_name,
        base_url=record.base_url,
        config=record.config or {},
        enabled=record.enabled,
    )


async def probe_model_connection(config: ModelRuntimeConfig) -> dict:
    definition = config.definition
    options = dict(definition.config or {})
    options["timeout_seconds"] = min(options.get("timeout_seconds", 60), 10)
    options["max_retries"] = 0
    config = replace(config, definition=replace(definition, config=options))
    started = perf_counter()
    try:
        model = build_model(config)

        async def infer() -> None:
            received = False
            async for _ in model.astream("请只回复 OK"):
                received = True
            if not received:
                raise ValueError("模型返回空响应")

        await asyncio.wait_for(infer(), timeout=15)
        return {
            "success": True,
            "stages": {"connect": "success", "authentication": "success", "inference": "success"},
            "latency_ms": round((perf_counter() - started) * 1000),
            "model": definition.model_name,
        }
    except (openai.AuthenticationError, openai.PermissionDeniedError):
        stage, code, message = "authentication", "MODEL_AUTH_FAILED", "模型服务认证失败"
    except openai.RateLimitError:
        stage, code, message = "inference", "MODEL_RATE_LIMITED", "模型服务请求受限"
    except (openai.APIConnectionError, TimeoutError):
        stage, code, message = "connect", "MODEL_CONNECTION_FAILED", "模型服务无法连接"
    except openai.NotFoundError:
        stage, code, message = "inference", "MODEL_NOT_FOUND", "模型不存在或不可调用"
    except ValueError as exc:
        if "凭证" in str(exc):
            stage, code, message = "authentication", "MODEL_CREDENTIAL_MISSING", "模型凭证缺失"
        else:
            stage, code, message = "inference", "MODEL_INFERENCE_FAILED", "模型推理失败"
    except openai.APIError:
        stage, code, message = "inference", "MODEL_INFERENCE_FAILED", "模型推理失败"
    return {"success": False, "stage": stage, "code": code, "message": message}


def saved_runtime_config(record) -> ModelRuntimeConfig:
    return resolve_model_config(definition_from_record(record), record.api_key_encrypted)


async def probe_saved_model(record) -> dict:
    try:
        return await probe_model_connection(saved_runtime_config(record))
    except ModelSecretConfigurationError:
        return {
            "success": False,
            "stage": "authentication",
            "code": "MODEL_CREDENTIAL_UNAVAILABLE",
            "message": "模型凭证暂不可用",
        }


async def probe_draft_model(values: dict, api_key: str | None) -> dict:
    return await probe_model_connection(
        ModelRuntimeConfig(
            definition=ModelDefinition(
                provider=values["provider"],
                model_name=values["model_name"],
                base_url=values.get("base_url"),
                config=values.get("config") or {},
            ),
            credential=api_key,
        )
    )
