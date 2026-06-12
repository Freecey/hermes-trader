"""Offline tests for the multi-provider LLM registry in research.py.

No network: the Anthropic branch is exercised against a stub client and the
chat-completions path is only resolution-tested.
"""
import pytest

from hermes_trader.agents import research


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("HERMES_LLM_PROVIDER", "HERMES_LLM_MODEL", "HERMES_LLM_BASE_URL",
                "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENAI_API_KEY",
                "GEMINI_API_KEY", "MINIMAX_API_KEY", "ANTHROPIC_API_KEY",
                "ANTHROPIC_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(research, "_anthropic_client_instance", None)
    yield


# ── resolution ──────────────────────────────────────────────────────────

def test_default_provider_is_openrouter_with_legacy_model_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k1")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6")
    provider, base_url, key, model = research._resolve_provider()
    assert provider == "openrouter"
    assert base_url == "https://openrouter.ai/api/v1/chat/completions"
    assert key == "k1"
    assert model == "anthropic/claude-sonnet-4-6"  # legacy env still honored


@pytest.mark.parametrize("provider,key_env,url_part", [
    ("openai", "OPENAI_API_KEY", "api.openai.com"),
    ("google", "GEMINI_API_KEY", "generativelanguage.googleapis.com"),
    ("minimax", "MINIMAX_API_KEY", "api.minimax.io"),
])
def test_openai_compatible_providers_resolve(monkeypatch, provider, key_env, url_part):
    monkeypatch.setenv("HERMES_LLM_PROVIDER", provider)
    monkeypatch.setenv(key_env, "sk-test")
    p, base_url, key, model = research._resolve_provider()
    assert p == provider
    assert url_part in base_url
    assert key == "sk-test"
    assert model  # every provider has a default model


def test_anthropic_provider_resolves_with_default_model(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    provider, base_url, key, model = research._resolve_provider()
    assert provider == "anthropic"
    assert base_url == ""  # native Messages API path, no chat-completions URL
    assert key == "sk-ant-test"
    assert model == "claude-opus-4-8"


def test_hermes_llm_model_overrides_any_provider(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("HERMES_LLM_MODEL", "claude-haiku-4-5")
    assert research._resolve_provider()[3] == "claude-haiku-4-5"


def test_base_url_override_enables_local_servers(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("HERMES_LLM_BASE_URL", "http://localhost:11434/v1/chat/completions")
    assert research._resolve_provider()[1].startswith("http://localhost:11434")


def test_unknown_provider_falls_back_to_openrouter(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PROVIDER", "doesnotexist")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    provider, base_url, _, _ = research._resolve_provider()
    assert provider == "openrouter"
    assert "openrouter.ai" in base_url


# ── call dispatch ───────────────────────────────────────────────────────

def test_missing_key_returns_empty_without_network(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PROVIDER", "openai")  # no OPENAI_API_KEY set
    assert research._call_ai("sys", "user") == ""


class _StubBlock:
    type = "text"
    text = "VERDICT TEXT"


class _StubMessages:
    def __init__(self, capture):
        self._capture = capture

    def create(self, **kwargs):
        self._capture.update(kwargs)
        return type("Resp", (), {"content": [_StubBlock()]})()


class _StubAnthropicClient:
    def __init__(self, capture):
        self.messages = _StubMessages(capture)


def test_anthropic_branch_uses_messages_api_shape(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    captured = {}
    monkeypatch.setattr(research, "_anthropic_client",
                        lambda api_key: _StubAnthropicClient(captured))
    out = research._call_ai("the system prompt", "the user message")
    assert out == "VERDICT TEXT"
    assert captured["model"] == "claude-opus-4-8"
    assert captured["system"] == "the system prompt"
    assert captured["messages"] == [{"role": "user", "content": "the user message"}]
    assert captured["max_tokens"] == 512
    assert "temperature" not in captured  # removed on recent Claude models


def test_anthropic_failure_is_loud_but_returns_empty(monkeypatch, caplog):
    monkeypatch.setenv("HERMES_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    class _Boom:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("billing exploded")

    monkeypatch.setattr(research, "_anthropic_client", lambda api_key: _Boom())
    with caplog.at_level("ERROR"):
        assert research._call_ai("s", "u") == ""
    assert any("FAILED" in r.message for r in caplog.records)
