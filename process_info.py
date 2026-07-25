"""Shared process-record shape exchanged by monitoring and UI components."""
from __future__ import annotations

from typing import TypedDict


class ProcessInfo(TypedDict):
    pid: int
    create_time: float
    comm: str
    name: str
    user: str
    sudo: bool
    cpu_percent: float
    mem_rss: int
    nice: int
    affinity: str
    ionice: str
    cmdline: str
