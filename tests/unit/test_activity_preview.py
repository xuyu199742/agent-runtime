"""活动预览处理认证字段及非 JSON 工具输出，不泄漏嵌套凭证。"""

import json

import pytest

from app.persistence.repositories.activity import preview


@pytest.mark.parametrize(
    "key",
    [
        "headers",
        "request_headers",
        "responseHeaders",
        "X-Auth",
        "customAuth",
        "auth",
        "authentication",
        "access_key",
        "accessKeyId",
        "client_secret",
        "credential",
        "credentials",
        "sessionid",
        "session_id",
        "sessionToken",
        "Authorization",
        "Proxy-Authorization",
        "X-API-Key",
        "Cookie",
        "Set-Cookie",
        "password",
        "api_key",
        "privateKey",
        "aws_secret_access_key",
        "refresh_token",
    ],
)
def test_nested_auth_fields_are_redacted(key):
    value = {
        "result": [{"nested": {key: {"value": "hidden-credential-value"}}}],
        "contentHash": "actual-hash",
        "token_count": 42,
        "max_tokens": 100,
    }
    result = preview(value)
    assert "hidden-credential-value" not in json.dumps(result)
    assert result["contentHash"] == "actual-hash"
    assert result["token_count"] == 42
    assert result["max_tokens"] == 100
    assert preview(result) == result
    assert "hidden-credential-value" not in json.dumps(preview(json.dumps(value)))


@pytest.mark.parametrize(
    "text",
    [
        "auth=hidden-credential-value",
        "access_key: hidden-credential-value",
        'clientSecret="hidden-credential-value with spaces"',
        "credentials='hidden-credential-value with spaces'",
        "https://example.test?sessionid=hidden-credential-value&safe=1",
        'response: {"auth": "hidden-credential-value"}',
        'response: {"client_secret": "hidden-credential-value\\" with spaces"}',
        "Authorization: Basic hidden-credential-value",
        "Authorization: Digest nonce=hidden-credential-value, token=other",
        "Cookie: value=hidden-credential-value; opaque=another-secret",
        "Bearer hidden-credential-value",
    ],
)
def test_unstructured_tool_result_auth_values_are_redacted(text):
    redacted = preview(text)
    assert "hidden-credential-value" not in str(redacted)
    assert preview(redacted) == redacted


def test_preview_keeps_ordinary_hash_and_metadata_strings():
    value = "contentHash=actual-hash; token_count=42; author=Alice; method=GET"
    assert preview(value) == value


def test_headers_are_hidden_as_a_whole_and_author_is_preserved():
    value = {
        "headers": {"X-Auth": "first-secret", "Custom-Header": "second-secret"},
        "requestHeaders": {"Unknown": "third-secret"},
        "response_headers": {"Arbitrary": "fourth-secret"},
        "XAuth": "fifth-secret",
        "author": "Alice",
        "contentHash": "actual-hash",
    }
    redacted = preview(value)
    assert redacted == {
        "headers": "[已脱敏]",
        "requestHeaders": "[已脱敏]",
        "response_headers": "[已脱敏]",
        "XAuth": "[已脱敏]",
        "author": "Alice",
        "contentHash": "actual-hash",
    }
    assert preview(redacted) == redacted
