#!/usr/bin/env python3
"""Load test for 1c-help MCP server. Calls tools via HTTP, reports RPS, latency, rate limits.

Usage:
  python scripts/load_test_mcp.py [--workers 10] [--duration 60] [--url URL]
  MCP_URL=http://localhost:8050/mcp python scripts/load_test_mcp.py

Requires: MCP + Qdrant running (e.g. make up). Set MCP_RATE_LIMIT_PER_MIN to test limit.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Defaults
DEFAULT_URL = os.environ.get("MCP_URL", "http://localhost:8050/mcp")
DEFAULT_WORKERS = 10
DEFAULT_DURATION_SEC = 60
RATE_LIMIT_MARKER = "Rate limit exceeded"


def call_mcp_tool(url: str, tool: str, args: dict, timeout: int = 30) -> tuple[str | None, float, str | None]:
    """Call one MCP tool. Returns (response_text, latency_sec, error)."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    ).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    start = time.perf_counter()
    err_msg = None
    text = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            content = data.get("result", {}).get("content", [{}])
            text = content[0].get("text", "") if content else ""
    except Exception as e:
        err_msg = str(e)
    elapsed = time.perf_counter() - start
    return (text, elapsed, err_msg)


# Tool names and sample arguments for mixed load
LOAD_SCENARIOS = [
    ("search_1c_help", {"query": "Формат", "limit": 5}),
    ("search_1c_help_keyword", {"query": "МенеджерКриптографии", "limit": 5}),
    ("get_1c_help_index_status", {}),
    ("search_1c_help", {"query": "Запрос.Выполнить", "limit": 3}),
    ("get_1c_code_answer", {"query": "как подписать данные", "limit": 2, "include_memory": False}),
]


def run_one(url: str, timeout: int, scenario_index: int) -> tuple[float, bool, bool]:
    """Run one request; returns (latency_sec, is_error, is_rate_limit)."""
    tool, args = LOAD_SCENARIOS[scenario_index % len(LOAD_SCENARIOS)]
    text, latency, err = call_mcp_tool(url, tool, args, timeout=timeout)
    is_error = err is not None
    is_rate_limit = (text or "") if not is_error else ""
    is_rate_limit = RATE_LIMIT_MARKER in is_rate_limit or (err and "429" in str(err))
    return (latency, is_error, is_rate_limit)


def main() -> int:
    parser = argparse.ArgumentParser(description="Load test 1c-help MCP")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent workers")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION_SEC, help="Run duration (seconds)")
    parser.add_argument("--url", type=str, default=DEFAULT_URL, help="MCP URL")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout per call")
    parser.add_argument("--output", type=str, default="", help="Write report to file (default: stdout)")
    args = parser.parse_args()

    url = args.url
    workers = max(1, args.workers)
    duration = max(1, args.duration)
    timeout = max(5, args.timeout)

    latencies: list[float] = []
    errors = 0
    rate_limits = 0
    total_requests = 0
    start_wall = time.perf_counter()
    end_wall = start_wall + duration
    scenario_idx = 0

    def tasks():
        nonlocal scenario_idx
        while time.perf_counter() < end_wall:
            idx = scenario_idx % len(LOAD_SCENARIOS)
            scenario_idx += 1
            yield idx

    task_iter = iter(tasks())
    batch: list[int] = []
    try:
        while time.perf_counter() < end_wall:
            for _ in range(workers * 2):
                try:
                    batch.append(next(task_iter))
                except StopIteration:
                    break
            if not batch:
                break
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(run_one, url, timeout, idx): idx for idx in batch}
                for fut in as_completed(futs):
                    lat, is_err, is_rl = fut.result()
                    total_requests += 1
                    latencies.append(lat)
                    if is_err:
                        errors += 1
                    if is_rl:
                        rate_limits += 1
            batch.clear()

    except KeyboardInterrupt:
        pass

    elapsed = time.perf_counter() - start_wall
    rps = total_requests / elapsed if elapsed > 0 else 0

    # Percentiles
    latencies.sort()
    n = len(latencies)
    if n == 0:
        p50 = p95 = p99 = 0.0
    else:
        p50 = latencies[int(n * 0.50) - 1] if n >= 1 else latencies[0]
        p95 = latencies[int(n * 0.95) - 1] if n >= 1 else latencies[-1]
        p99 = latencies[int(n * 0.99) - 1] if n >= 1 else latencies[-1]
    avg_lat = statistics.mean(latencies) if latencies else 0.0

    report_lines = [
        "=== MCP load test report ===",
        f"URL: {url}",
        f"Workers: {workers}, Duration: {duration}s",
        f"Total requests: {total_requests}",
        f"RPS: {rps:.2f}",
        f"Latency (s): avg={avg_lat:.3f} p50={p50:.3f} p95={p95:.3f} p99={p99:.3f}",
        f"Errors: {errors}",
        f"Rate limit responses: {rate_limits}",
        "",
    ]
    if rate_limits > 0:
        report_lines.append(
            "Tip: MCP_RATE_LIMIT_PER_MIN limits requests/min; increase or set 0 to disable."
        )

    report = "\n".join(report_lines)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(report)
    else:
        print(report)

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
