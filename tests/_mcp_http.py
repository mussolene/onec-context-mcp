"""Helpers for session-aware streamable-http MCP integration tests."""

from __future__ import annotations

import json
import os
import urllib.request
from urllib.error import HTTPError, URLError

import pytest


class StreamableHttpMcpClient:
    """Minimal MCP client for streamable-http tests."""

    def __init__(self, url: str, timeout: int = 15) -> None:
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._request_id = 0

    @classmethod
    def from_env_or_skip(cls) -> StreamableHttpMcpClient:
        url = os.environ.get("MCP_URL", "http://localhost:8050/mcp")
        client = cls(url=url)
        try:
            client.initialize()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            pytest.skip(f"MCP not available: {exc}")
        return client

    def initialize(self) -> None:
        if self.session_id:
            return
        response, payload = self._post(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "pytest-mcp", "version": "1.0"},
            },
            include_session=False,
        )
        self.session_id = response.headers.get("mcp-session-id")
        if not self.session_id:
            raise RuntimeError(f"MCP session ID missing in initialize response: {payload}")

    def list_tools(self) -> list[str]:
        payload = self._rpc("tools/list", {})
        return [item["name"] for item in payload.get("result", {}).get("tools", [])]

    def call_tool(self, tool: str, args: dict) -> str:
        payload = self._rpc("tools/call", {"name": tool, "arguments": args})
        content = payload.get("result", {}).get("content", [{}])
        return content[0].get("text", "") if content else ""

    def _rpc(self, method: str, params: dict) -> dict:
        self.initialize()
        _, payload = self._post(method, params, include_session=True)
        return self._parse_payload(payload)

    def _post(self, method: str, params: dict, *, include_session: bool) -> tuple[object, str]:
        self._request_id += 1
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if include_session and self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.url, data=body, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp, resp.read().decode("utf-8")

    @staticmethod
    def _parse_payload(raw: str) -> dict:
        raw = raw.strip()
        if not raw:
            return {}
        data_lines = [line[6:] for line in raw.splitlines() if line.startswith("data: ")]
        if data_lines:
            return json.loads(data_lines[-1])
        return json.loads(raw)
