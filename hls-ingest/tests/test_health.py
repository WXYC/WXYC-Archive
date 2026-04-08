"""Tests for the health endpoint under various states."""

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

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
