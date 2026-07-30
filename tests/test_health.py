"""Prove the app boots, the probe Railway depends on answers, and no response leaks the key."""

from fastapi.testclient import TestClient

from app.main import WEB_DIST, app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_reports_key_presence_but_never_the_key():
    r = client.get("/health")
    assert "anthropic_key_configured" in r.text
    assert "sk-ant-" not in r.text  # the probe must never leak the credential


def test_root_serves_bundle_when_built_else_says_it_is_not():
    """Phase 0c made this conditional: once `web/dist` exists the static mount owns "/",
    and before that a JSON placeholder states plainly that the UI isn't built. Asserting
    whichever branch actually applies keeps the test honest in both states."""
    r = client.get("/")
    assert r.status_code == 200
    if WEB_DIST.is_dir():
        assert "<!doctype html" in r.text.lower()
        assert 'id="root"' in r.text
    else:
        assert "hint" in r.json()


def test_health_reports_whether_the_bundle_is_present():
    assert client.get("/health").json()["web_bundle_present"] == WEB_DIST.is_dir()
