"""受控 ticket.create 示例；服务端 URL 和凭证仅由部署配置提供。"""

import hashlib
import json
from urllib.parse import quote, urlparse

import httpx

from app.runtime.effects.contract import EffectIdentity, EffectObservation


def _ticket_result(payload: dict) -> EffectObservation:
    ticket_id = payload.get("ticket_id")
    if not isinstance(ticket_id, str) or not ticket_id:
        raise ValueError("工单服务未返回 ticket_id")
    return EffectObservation.succeeded(
        json.dumps({"ticket_id": ticket_id}, ensure_ascii=False, sort_keys=True), ticket_id
    )


class TicketCreateProvider:
    def __init__(self, namespace: str, base_url: str, token: str, *, transport=None):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("工单服务必须配置 HTTPS URL")
        if not namespace or not token:
            raise ValueError("工单服务 namespace 和凭证不能为空")
        self.namespace = namespace
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport

    def identity(self, args: dict) -> EffectIdentity:
        key = args.get("ticket_key")
        title = args.get("title")
        if not isinstance(key, str) or not key.strip() or len(key) > 150:
            raise ValueError("ticket_key 必须是非空且长度不超过 150 的稳定业务键")
        if not isinstance(title, str) or not title.strip() or len(title) > 500:
            raise ValueError("title 必须是非空且长度不超过 500 的字符串")
        if set(args) != {"ticket_key", "title"}:
            raise ValueError("ticket.create 仅接受 ticket_key 和 title")
        normalized = {"ticket_key": key.strip(), "title": title.strip()}
        request_hash = hashlib.sha256(
            json.dumps(
                normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        return EffectIdentity(
            self.namespace,
            "ticket.create",
            f"ticket:create:{normalized['ticket_key']}",
            1,
            request_hash,
        )

    async def invoke(self, args: dict, business_key: str) -> EffectObservation:
        headers = {"Authorization": f"Bearer {self.token}", "Idempotency-Key": business_key}
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, trust_env=False, transport=self.transport
        ) as client:
            response = await client.post(
                f"{self.base_url}/tickets",
                headers=headers,
                json={"ticket_key": args["ticket_key"].strip(), "title": args["title"].strip()},
            )
            response.raise_for_status()
            return _ticket_result(response.json())

    async def reconcile(self, identity: EffectIdentity) -> EffectObservation:
        headers = {"Authorization": f"Bearer {self.token}"}
        key = quote(identity.business_key, safe="")
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, trust_env=False, transport=self.transport
        ) as client:
            response = await client.get(
                f"{self.base_url}/tickets/by-idempotency-key/{key}", headers=headers
            )
            if response.status_code == 404:
                # 查不到记录不能证明先前在途请求未来不会落地。
                return EffectObservation.unknown()
            response.raise_for_status()
            return _ticket_result(response.json())
