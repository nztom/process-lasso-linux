"""Shared process-record shape exchanged by monitoring and UI components."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import ClassVar, TypedDict

from policy_models import EffectiveProcessPolicy


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
