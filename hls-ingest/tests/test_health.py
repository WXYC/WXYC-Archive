"""Tests for the health endpoint under various states."""

import pytest

from health import create_health_app

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture
def healthy_app():
    """Create a health app that reports healthy status."""
    return create_health_app(is_healthy=lambda: True)


@pytest.fixture
def unhealthy_app():
    """Create a health app that reports unhealthy status."""
    return create_health_app(is_healthy=lambda: False)


@pytest.mark.asyncio
async def test_health_returns_200_when_healthy(healthy_app, aiohttp_client):
    client = await aiohttp_client(healthy_app)
    resp = await client.get("/health")
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"
    assert body["ffmpeg"] is True


@pytest.mark.asyncio
async def test_health_returns_503_when_unhealthy(unhealthy_app, aiohttp_client):
    client = await aiohttp_client(unhealthy_app)
    resp = await client.get("/health")
    assert resp.status == 503
    body = await resp.json()
    assert body["status"] == "degraded"
    assert body["ffmpeg"] is False


@pytest.mark.asyncio
async def test_health_content_type(healthy_app, aiohttp_client):
    client = await aiohttp_client(healthy_app)
    resp = await client.get("/health")
    assert "application/json" in resp.headers["Content-Type"]


@pytest.mark.asyncio
async def test_unknown_route_returns_404(healthy_app, aiohttp_client):
    client = await aiohttp_client(healthy_app)
    resp = await client.get("/nonexistent")
    assert resp.status == 404


class TestHealthTypeAnnotations:
    """Verify proper type annotations instead of bare builtin callable."""

    def test_create_health_app_uses_callable_type(self):
        import inspect

        sig = inspect.signature(create_health_app)
        param = sig.parameters["is_healthy"]
        assert (
            param.annotation is not callable
        ), "is_healthy should use Callable[[], bool], not the builtin callable"

    def test_run_health_server_uses_callable_type(self):
        import inspect
        from health import run_health_server

        sig = inspect.signature(run_health_server)
        param = sig.parameters["is_healthy"]
        assert (
            param.annotation is not callable
        ), "is_healthy should use Callable[[], bool], not the builtin callable"
