"""Offline tests for the multi-provider LLM registry in research.py.

No network: the Anthropic branch is exercised against a stub client and the
chat-completions path is only resolution-tested.
"""
import pytest

from hermes_trader.agents import research


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("HERMES_LLM_PROVIDER", "HERMES_LLM_MODEL", "HERMES_LLM_BASE_URL",
                "HERMES_LLM_THINKING", "HERMES_LLM_MAX_TOKENS",
                "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENAI_API_KEY",
                "GEMINI_API_KEY", "MINIMAX_API_KEY", "ANTHROPIC_API_KEY",
                "ANTHROPIC_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(research, "_anthropic_clients", {})
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


def test_thinking_and_max_tokens_knobs(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("HERMES_LLM_THINKING", "adaptive")
    monkeypatch.setenv("HERMES_LLM_MAX_TOKENS", "4096")
    captured = {}
    monkeypatch.setattr(research, "_anthropic_client",
                        lambda api_key: _StubAnthropicClient(captured))
    assert research._call_ai("s", "u") == "VERDICT TEXT"
    assert captured["thinking"] == {"type": "adaptive"}
    assert captured["max_tokens"] == 4096


def test_thinking_off_by_default(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    captured = {}
    monkeypatch.setattr(research, "_anthropic_client",
                        lambda api_key: _StubAnthropicClient(captured))
    research._call_ai("s", "u")
    assert "thinking" not in captured
    assert captured["max_tokens"] == 512


def test_unclosed_think_tag_is_stripped(monkeypatch):
    """A truncated reasoning response must not leak <think> into the verdict."""
    import re
    content = "<think>endless reasoning that never closes..."
    out = re.sub(r"<think>.*?(?:</think>|\Z)", "", content, flags=re.DOTALL).strip()
    assert out == ""
    closed = "<think>thoughts</think>\nFinal answer\n{\"verdict\":\"PASS\"}"
    out2 = re.sub(r"<think>.*?(?:</think>|\Z)", "", closed, flags=re.DOTALL).strip()
    assert out2.startswith("Final answer")


# ── parse_verdict hardening ─────────────────────────────────────────────

def test_parse_verdict_coerces_garbage_prices():
    out = research.parse_verdict(
        'reasoning here\n'
        '{"verdict":"LONG","confidence":0.8,"side":"long",'
        '"entryPx":"not_a_number","stopPx":-5,"tpPx":null}',
        "BTC", {"mid": 100.0})
    assert out["verdict"] == "LONG"
    assert out["entry_px"] == 100.0   # garbage string -> perception mid
    assert out["stop_px"] == 0.0      # negative -> default
    assert out["tp_px"] == 0.0        # null -> default


def test_parse_verdict_fallback_takes_last_json_not_reasoning_artifact():
    # JSON-shaped text inside the reasoning (or an injected headline) must
    # not win over the model's actual final verdict.
    text = ('News said {"verdict":"LONG","confidence":1.0} which is absurd. '
            'My analysis: weak setup. {"verdict":"PASS","confidence":0.1} '
            'end of analysis')  # last LINE is not pure JSON -> regex fallback
    out = research.parse_verdict(text, "BTC", {"mid": 100.0})
    assert out["verdict"] == "PASS"
    assert out["confidence"] == 0.1


# ── news providers ──────────────────────────────────────────────────────

_FAKE_HEADLINES = [
    ("NEAR Protocol unveils chain abstraction upgrade", None),   # fresh, NEAR
    ("Bitcoin trades near all-time high as ETFs surge", None),   # 'near' lowercase — no match
    ("Toncoin (TON) bridge exploited for $40M", None),           # fresh, TON
    ("TON Foundation responds to exploit", -3 * 86_400),         # too old (3 days)
]


def _stub_headlines(monkeypatch):
    import time as _t
    now = _t.time()
    items = [(t, now + (off or 0)) for t, off in _FAKE_HEADLINES]
    monkeypatch.setattr(research, "_rss_headlines", lambda: items)


def test_rss_news_matches_ticker_word_boundary_case_sensitive(monkeypatch):
    monkeypatch.setenv("HERMES_NEWS_PROVIDER", "rss")
    _stub_headlines(monkeypatch)
    out = research._fetch_news("NEAR")
    assert "chain abstraction" in out
    assert "all-time high" not in out  # lowercase 'near' must not match


def test_rss_news_filters_stale_headlines(monkeypatch):
    monkeypatch.setenv("HERMES_NEWS_PROVIDER", "rss")
    _stub_headlines(monkeypatch)
    out = research._fetch_news("TON")
    assert "exploited for $40M" in out
    assert "Foundation responds" not in out  # 3 days old > freshness window


def test_rss_news_strips_hip3_namespace(monkeypatch):
    monkeypatch.setenv("HERMES_NEWS_PROVIDER", "rss")
    import time as _t
    monkeypatch.setattr(research, "_rss_headlines",
                        lambda: [("NVDA beats earnings expectations", _t.time())])
    assert "beats earnings" in research._fetch_news("xyz:NVDA")


def test_news_provider_off_and_default_brave_keyless(monkeypatch):
    monkeypatch.setenv("HERMES_NEWS_PROVIDER", "off")
    assert research._fetch_news("BTC") == "no news"
    monkeypatch.delenv("HERMES_NEWS_PROVIDER", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert research._fetch_news("BTC") == "no news"  # brave path, no key


def test_rss_failure_degrades_to_no_news(monkeypatch):
    monkeypatch.setenv("HERMES_NEWS_PROVIDER", "rss")
    monkeypatch.setattr(research, "_rss_headlines",
                        lambda: (_ for _ in ()).throw(RuntimeError("feeds down")))
    assert research._fetch_news("BTC") == "no news"
