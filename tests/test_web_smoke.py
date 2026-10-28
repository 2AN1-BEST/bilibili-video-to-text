"""Web 服务冒烟测试：确认重构后的路由仍可用（不触发真实下载）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_index_page_is_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()


def test_invalid_url_returns_400():
    resp = client.post("/api/transcribe", json={"url": "https://example.com/v/1"})
    assert resp.status_code == 400


def test_invalid_model_returns_400():
    resp = client.post(
        "/api/transcribe",
        json={"url": "https://www.bilibili.com/video/BV1GJ411x7h7", "model": "huge"},
    )
    assert resp.status_code == 400


def test_unknown_task_returns_404():
    assert client.get("/api/task/does-not-exist").status_code == 404
    assert client.get("/api/download/does-not-exist").status_code == 404
