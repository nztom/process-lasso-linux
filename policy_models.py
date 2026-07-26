"""Immutable read-model values for effective process policies."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AbsoluteNicePolicy:
    """An absolute Linux nice value."""

    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or not -20 <= self.value <= 19:
            raise ValueError("absolute nice value must be an integer from -20 to 19")


@dataclass(frozen=True)
class OffsetNicePolicy:
    """A relative nice adjustment constrained to Linux nice bounds."""

    offset: int
    floor: int = -15
    ceiling: int = 19

    def __post_init__(self) -> None:
        if type(self.offset) is not int:
            raise ValueError("nice offset must be an integer")
        if type(self.floor) is not int or type(self.ceiling) is not int:
            raise ValueError("nice bounds must be integers")
        if not -20 <= self.floor <= self.ceiling <= 19:
            raise ValueError(
                "nice bounds must satisfy -20 <= floor <= ceiling <= 19"
            )


NicePolicy = AbsoluteNicePolicy | OffsetNicePolicy


@dataclass(frozen=True)
class IoPriorityPolicy:
    """An effective Linux I/O scheduling class and optional class level."""

    io_class: int
    level: int | None = None

    def __post_init__(self) -> None:
        if type(self.io_class) is not int or not 0 <= self.io_class <= 3:
            raise ValueError("I/O priority class must be an integer from 0 to 3")
        if self.level is not None and (
            type(self.level) is not int or not 0 <= self.level <= 7
        ):
            raise ValueError("I/O priority level must be None or an integer from 0 to 7")


@dataclass(frozen=True)
class EffectiveProcessPolicy:
    """Final per-field policy produced by all matching enabled rules."""

    affinity: str | None = None
    nice: NicePolicy | None = None
    ionice: IoPriorityPolicy | None = None


def format_nice_policy(policy: NicePolicy) -> str:
    """Return the stable user-facing representation of a nice policy."""
    if isinstance(policy, AbsoluteNicePolicy):
        return f"Absolute {policy.value}"
    if isinstance(policy, OffsetNicePolicy):
        return f"Offset {policy.offset:+d} [{policy.floor}, {policy.ceiling}]"
    raise TypeError(f"unsupported nice policy: {type(policy).__name__}")
