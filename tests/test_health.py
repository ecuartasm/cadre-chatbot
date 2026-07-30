"""Phase 0a: prove the app boots and the probe Railway depends on actually answers."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_reports_key_presence_but_never_the_key():
    body = r_text = client.get("/health").text
    assert "anthropic_key_configured" in body
    assert "sk-ant-" not in r_text  # the probe must never leak the credential


def test_root_is_honest_about_what_is_unbuilt():
    r = client.get("/")
    assert r.status_code == 200
    assert "not_yet_built" in r.json()
