"""Shared process-record shape exchanged by monitoring and UI components."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import ClassVar, TypedDict

from policy_models import EffectiveProcessPolicy


@dataclass(frozen=True)
class ProcessIdentity:
    """Stable identity for one lifetime of a Linux process ID."""

    pid: int
    create_time: float

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "ProcessIdentity":
        return cls(
            pid=int(record["pid"]),
            create_time=float(record.get("create_time", 0.0)),
        )


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


@dataclass(frozen=True)
class ProcessSnapshot(Mapping[str, object]):
    """Immutable, GUI-safe copy of one observed process record.

    The mapping interface is temporary compatibility for dictionary-based GUI
    consumers while the typed process-policy view is introduced incrementally.
    """

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

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "pid", "create_time", "comm", "name", "user", "sudo",
        "cpu_percent", "mem_rss", "nice", "affinity", "ionice", "cmdline",
    )

    @classmethod
    def from_info(cls, info: ProcessInfo) -> "ProcessSnapshot":
        """Detach an immutable snapshot from a worker-owned mutable record."""
        return cls(
            pid=info["pid"],
            create_time=info["create_time"],
            comm=info["comm"],
            name=info["name"],
            user=info["user"],
            sudo=info["sudo"],
            cpu_percent=info["cpu_percent"],
            mem_rss=info["mem_rss"],
            nice=info["nice"],
            affinity=info["affinity"],
            ionice=info["ionice"],
            cmdline=info["cmdline"],
        )

    @classmethod
    def from_mapping(cls, info: Mapping[str, object]) -> "ProcessSnapshot":
        """Normalize legacy/test mappings at the GUI compatibility boundary."""
        name = str(info.get("name", ""))
        return cls(
            pid=int(info["pid"]),
            create_time=float(info.get("create_time", 0.0)),
            comm=str(info.get("comm", name)),
            name=name,
            user=str(info.get("user", "")),
            sudo=bool(info.get("sudo", False)),
            cpu_percent=float(info.get("cpu_percent", 0.0)),
            mem_rss=int(info.get("mem_rss", 0)),
            nice=int(info.get("nice", 0)),
            affinity=str(info.get("affinity", "")),
            ionice=str(info.get("ionice", "")),
            cmdline=str(info.get("cmdline", "")),
        )

    def __getitem__(self, key: str) -> object:
        if key not in self._FIELDS:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._FIELDS)

    def __len__(self) -> int:
        return len(self._FIELDS)


@dataclass(frozen=True)
class ProcessPolicyView(Mapping[str, object]):
    """Immutable observed state joined with effective and runtime policy."""

    observed: ProcessSnapshot
    effective_policy: EffectiveProcessPolicy
    manually_overridden: bool = False

    def __getitem__(self, key: str) -> object:
        return self.observed[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.observed)

    def __len__(self) -> int:
        return len(self.observed)


@dataclass(frozen=True)
class ThreadSnapshot:
    """Immutable result of one lazy thread sample."""

    tid: int
    start_time_ticks: int
    name: str
    cpu_percent: float | None
    nice: int
    affinity: str
    ionice: str

    @classmethod
    def from_mapping(cls, thread: Mapping[str, object]) -> "ThreadSnapshot":
        """Normalize custom providers at the process-table boundary."""
        tid = int(thread["tid"])
        cpu = thread.get("cpu_percent")
        return cls(
            tid=tid,
            start_time_ticks=int(thread.get("start_time_ticks", 0)),
            name=str(thread.get("name", tid)),
            cpu_percent=None if cpu is None else float(cpu),
            nice=int(thread.get("nice", 0)),
            affinity=str(thread.get("affinity", "")),
            ionice=str(thread.get("ionice", "")),
        )
