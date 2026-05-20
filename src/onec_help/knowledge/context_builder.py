"""Thin wrapper over task orchestrator for compact AI-oriented 1C task context."""

from __future__ import annotations

from .orchestrator.task_orchestrator import ContextRequest, build_context, resolve_1c_task_context

__all__ = ["ContextRequest", "build_context", "resolve_1c_task_context"]
