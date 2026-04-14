"""HTTP health endpoint for the HLS ingest service."""

import json
import logging
from collections.abc import Callable
from aiohttp import web

logger = logging.getLogger(__name__)


def create_health_app(is_healthy: Callable[[], bool]) -> web.Application:
    """Create an aiohttp application with a /health endpoint.

    Args:
        is_healthy: Callable that returns True if the service is healthy.
            Typically checks whether ffmpeg is alive.

    Returns:
        An aiohttp web.Application ready to be run.
    """
    app = web.Application()

    async def health_handler(request: web.Request) -> web.Response:
        healthy = is_healthy()
        status_code = 200 if healthy else 503
        body = json.dumps({"status": "ok" if healthy else "degraded", "ffmpeg": healthy})
        return web.Response(status=status_code, text=body, content_type="application/json")

    app.router.add_get("/health", health_handler)
    return app


async def run_health_server(port: int, is_healthy: Callable[[], bool]) -> web.AppRunner:
    """Start the health endpoint HTTP server.

    Args:
        port: TCP port to listen on.
        is_healthy: Callable returning current health status.

    Returns:
        The running AppRunner (caller is responsible for cleanup).
    """
    app = create_health_app(is_healthy)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health endpoint listening on :%d/health", port)
    return runner
