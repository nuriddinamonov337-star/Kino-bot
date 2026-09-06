"""HTTP liveness/readiness used by Docker and Railway."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import text

from app.database.session import Database

logger = logging.getLogger(__name__)


class HealthServer:
    def __init__(self, database: Database, port: int) -> None:
        self._database = database
        self._port = port
        self._server: asyncio.AbstractServer | None = None
        self.started_at = datetime.now(UTC)

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, host="0.0.0.0", port=self._port)
        logger.info("Health server listening on port %s", self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.read(1024)
            payload, status = await self._payload()
            body = json.dumps(payload).encode("utf-8")
            writer.write(
                f"HTTP/1.1 {status} {'OK' if status == 200 else 'Service Unavailable'}\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n".encode("ascii")
                + body
            )
            await writer.drain()
        except Exception:
            logger.exception("Health check handler failed")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _payload(self) -> tuple[dict[str, object], int]:
        database_ok = False
        try:
            async with self._database.session() as session:
                await session.execute(text("SELECT 1"))
            database_ok = True
        except Exception:
            logger.exception("Health check could not query PostgreSQL")
        payload = {
            "status": "ok" if database_ok else "degraded",
            "database": "ok" if database_ok else "error",
            "started_at": self.started_at.isoformat(),
        }
        return payload, 200 if database_ok else 503
