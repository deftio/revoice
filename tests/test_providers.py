"""Provider factory, HTTP providers (httpx monkeypatched), stub branches, extract_json."""

import httpx
import pytest

from revoice.config import ProviderConfig
from revoice.providers import make_provider
from revoice.providers.base import extract_json


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


def capture_post(monkeypatch, payload):
    calls = {}

    def post(url, **kw):
        calls["url"] = url
        calls.update(kw)
        return FakeResp(payload)

    monkeypatch.setattr(httpx, "post", post)
    return calls


def test_make_provider_kinds():
    for kind in ("stub", "anthropic", "ollama", "openrouter", "openai_compat"):
        assert make_provider(ProviderConfig(kind=kind)) is not None
    with pytest.raises(ValueError):
        make_provider(ProviderConfig(kind="nope"))


def test_ollama(monkeypatch):
    calls = capture_post(monkeypatch, {"message": {"content": "hi"}})
    p = make_provider(ProviderConfig(kind="ollama"))
    assert p.complete("sys", "usr") == "hi"
    assert calls["url"] == "http://localhost:11434/api/chat"
    body = calls["json"]
    assert body["think"] is False
    assert body["stream"] is False
    assert body["model"] == "gemma3:27b"
    assert body["messages"][0] == {"role": "system", "content": "sys"}


def test_ollama_custom_base(monkeypatch):
    calls = capture_post(monkeypatch, {"message": {"content": "x"}})
    p = make_provider(ProviderConfig(kind="ollama", base_url="http://h:1/", model="m"))
    p.complete("s", "u")
    assert calls["url"] == "http://h:1/api/chat"
    assert calls["json"]["model"] == "m"


def test_anthropic_no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = make_provider(ProviderConfig(kind="anthropic"))
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        p.complete("s", "u")


def test_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sekret")
    calls = capture_post(
        monkeypatch,
        {"content": [{"type": "text", "text": "he"}, {"type": "tool_use"}, {"type": "text", "text": "llo"}]},
    )
    p = make_provider(ProviderConfig(kind="anthropic"))
    assert p.complete("s", "u") == "hello"
    assert calls["headers"]["x-api-key"] == "sekret"
    assert calls["json"]["model"] == "claude-sonnet-5"
    assert calls["json"]["system"] == "s"


def test_openrouter_no_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    p = make_provider(ProviderConfig(kind="openrouter", api_key_env=""))
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        p.complete("s", "u")


def test_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "orkey")
    calls = capture_post(monkeypatch, {"choices": [{"message": {"content": "ok"}}]})
    p = make_provider(ProviderConfig(kind="openrouter", api_key_env="OPENROUTER_API_KEY", model="a/b"))
    assert p.complete("s", "u") == "ok"
    assert calls["json"]["reasoning"] == {"enabled": False}
    assert calls["headers"]["authorization"] == "Bearer orkey"
    assert calls["url"] == "https://openrouter.ai/api/v1/chat/completions"


def test_openai_compat_no_key(monkeypatch):
    calls = capture_post(monkeypatch, {"choices": [{"message": {"content": "y"}}]})
    p = make_provider(ProviderConfig(kind="openai_compat", api_key_env=""))
    assert p.complete("s", "u") == "y"
    assert "authorization" not in calls["headers"]
    assert calls["url"] == "http://localhost:8080/v1/chat/completions"
    assert calls["json"]["messages"][0]["content"].endswith("/no_think")


def test_openai_compat_bearer(monkeypatch):
    monkeypatch.setenv("MY_KEY", "k123")
    calls = capture_post(monkeypatch, {"choices": [{"message": {"content": "y"}}]})
    p = make_provider(ProviderConfig(kind="openai_compat", api_key_env="MY_KEY", base_url="http://x/v1"))
    p.complete("s", "u")
    assert calls["headers"]["authorization"] == "Bearer k123"


# ---- stub branches ----

def test_stub_branches(stub):
    assert stub.complete("You are a test", "x") == '{"ok": true, "who": "stub"}'
    assert stub.complete("RUBRIC_JUDGE\n- alpha: best\n- beta: worst", "x") == "alpha"
    assert stub.complete("RUBRIC_JUDGE no choices here", "x") == "unknown"
    assert stub.complete("COHESION_EDIT", "span text") == "span text"
    assert stub.complete("anything else", "x") == "[stub completion]"
    fiction = stub.complete("CLASSIFY_DOC", "Once upon a time she said TODO ???")
    assert '"fiction"' in fiction and '"brain_dump"' in fiction
    assert stub.complete("CLASSIFY_DOC", "") is not None
    assert "voice_summary" in stub.complete("BUILD_PROFILE", "x")


def test_stub_complete_json(stub):
    out = stub.complete_json("You are a test", "x")
    assert out == {"ok": True, "who": "stub"}


# ---- extract_json ----

def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('<think>blah</think>{"a": 1}') == {"a": 1}
    assert extract_json('reasoning...</think>{"a": 2}') == {"a": 2}
    assert extract_json('```json\n{"a": 3}\n```') == {"a": 3}
    assert extract_json('prefix text {"a": {"b": 4}} suffix') == {"a": {"b": 4}}
    assert extract_json("noise [1, 2, 3] tail") == [1, 2, 3]
    with pytest.raises(ValueError, match="no JSON"):
        extract_json("nothing here")
