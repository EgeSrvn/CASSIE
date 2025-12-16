import os
from fastapi.testclient import TestClient


def test_register_with_long_password(monkeypatch):
    # use in-memory sqlite for tests to avoid requiring a live Postgres
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    # import app after setting env var so db engine is created against sqlite
    from backend.api.main import create_app

    app = create_app()
    client = TestClient(app)

    long_password = "p" * 100
    resp = client.post("/api/auth/register", json={"email": "long@example.com", "password": long_password})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "long@example.com"