"""Routing the model call through a compatible gateway instead of api.anthropic.com.

The deployed instance needs this because the key Cadre supplied for the project is **OpenRouter's**
(`sk-or-v1-…`), not an Anthropic key. Sent to api.anthropic.com it is a flat 401 with no hint about
why — the prefix is the only clue, and only if you happen to know it.

`ANTHROPIC_BASE_URL` unset is the default and means today's behaviour exactly, so nothing about
local development changes. That matters: `count_tokens` is **404 on OpenRouter**, so the prefix
measurement and its live test have to keep talking to Anthropic directly.

⚠️ The trap these tests exist for: the SDK appends `/v1/messages` itself, so a base URL ending in
`/v1` produces `/v1/v1/messages` and a 404 whose body is an HTML page. The SDK surfaces that as
`NotFoundError` with a wall of markup and nothing about the cause. It cost a round trip.
"""

from __future__ import annotations

import importlib
import os

import pytest


def _reload_client(monkeypatch, base_url: str | None):
    """`BASE_URL` is resolved at import, like `MODEL` — so a test must reimport, not monkeypatch."""
    if base_url is None:
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", base_url)
    import app.llm.client as c

    return importlib.reload(c)


def test_unset_means_direct_anthropic(monkeypatch):
    """The default must be untouched. A gateway that switched itself on would silently reroute
    every developer's traffic through a third party."""
    c = _reload_client(monkeypatch, None)
    try:
        assert c.BASE_URL is None
        assert c.model_info()["api_base"] == "https://api.anthropic.com"
        assert c.model_info()["via_gateway"] is False
        assert c.base_url_warning() is None
    finally:
        _reload_client(monkeypatch, None)


def test_a_gateway_is_reported_not_hidden(monkeypatch):
    """`/health` must say WHERE the model is called, not only which model. 'A key is configured'
    and 'that key works against the endpoint we call' are different claims."""
    c = _reload_client(monkeypatch, "https://openrouter.ai/api")
    try:
        assert c.BASE_URL == "https://openrouter.ai/api"
        assert c.model_info()["api_base"] == "https://openrouter.ai/api"
        assert c.model_info()["via_gateway"] is True
        assert c.base_url_warning() is None, "a correct base URL must not warn"
    finally:
        _reload_client(monkeypatch, None)


@pytest.mark.parametrize(
    "bad",
    ["https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/", "https://x.example/v1"],
)
def test_a_trailing_v1_is_caught_at_startup(monkeypatch, bad: str):
    """The whole reason this warning exists. Every request would 404 with an HTML body."""
    c = _reload_client(monkeypatch, bad)
    try:
        w = c.base_url_warning()
        assert w is not None, f"{bad} would 404 on every request and was not flagged"
        assert "/v1" in w and "404" in w
    finally:
        _reload_client(monkeypatch, None)


def test_an_empty_string_is_treated_as_unset(monkeypatch):
    """Railway variables are strings; clearing one in the dashboard can leave `""` rather than
    removing it. An empty base URL must mean 'direct', not a request to the empty host."""
    c = _reload_client(monkeypatch, "")
    try:
        assert c.BASE_URL is None
        assert c.model_info()["via_gateway"] is False
    finally:
        _reload_client(monkeypatch, None)


def test_the_gateway_does_not_change_anything_downstream():
    """The seam's claim, asserted rather than assumed: routing is a client concern only. If the
    gateway leaked into cost, marker handling or the corpus, this stops being a one-line change."""
    from pathlib import Path

    root = Path(__file__).parent.parent
    for f in ("app/obs/cost.py", "app/llm/prompt.py", "app/api/chat.py", "app/knowledge/loader.py"):
        src = (root / f).read_text(encoding="utf-8")
        assert "BASE_URL" not in src and "openrouter" not in src.lower(), (
            f"{f} knows about the gateway — routing belongs in client.py alone"
        )


def test_the_model_id_needs_no_translation():
    """Verified live against OpenRouter: `claude-haiku-4-5` and `claude-sonnet-5` are accepted
    verbatim and normalised server-side to `anthropic/claude-haiku-4.5`. So `models.py` stays the
    single source of per-model truth and no id mapping exists to drift."""
    from app.llm.models import MODELS

    for mid in MODELS:
        assert "/" not in mid, (
            f"{mid} looks gateway-namespaced; model ids must stay provider-neutral"
        )


@pytest.mark.skipif(
    os.getenv("ANTHROPIC_BASE_URL") not in (None, ""),
    reason="count_tokens is 404 on OpenRouter — prefix measurement needs Anthropic directly",
)
def test_count_tokens_is_only_expected_without_a_gateway():
    """Documents the one capability a gateway does not provide, as a skip rather than a comment —
    so running the suite against a gateway reports it instead of failing mysteriously."""
    assert True
