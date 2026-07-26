"""Coordination boundary for process exit and PID-reuse cleanup.

Subsystems retain ownership of their runtime collections.  This coordinator
only guarantees that each owner is notified once when Monitor detects that a
process identity has ended.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class _PidRuntimeOwner(Protocol):
    def forget_pid(self, pid: int) -> None: ...


class ProcessRuntimeCleanup:
    """Notify all runtime-state owners that one PID identity has ended."""

    def __init__(
        self,
        rule_engine: _PidRuntimeOwner,
        probalance: _PidRuntimeOwner,
        forget_monitor_state: Callable[[int], None],
    ) -> None:
        self._rule_engine = rule_engine
        self._probalance = probalance
        self._forget_monitor_state = forget_monitor_state

    def forget_pid(self, pid: int) -> None:
        """Clear one identity from every owner exactly once."""
        self._rule_engine.forget_pid(pid)
        self._probalance.forget_pid(pid)
        self._forget_monitor_state(pid)
