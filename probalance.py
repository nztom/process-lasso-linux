"""ProBalance state machine: throttle CPU hogs, restore when calm."""
from __future__ import annotations

import logging
import os
import psutil
from dataclasses import dataclass, field
from typing import Optional

import utils
from process_info import (
    ProcessIdentity,
    ProcessInfo,
    ProcessPolicyView,
    ProcessSnapshot,
)

log = logging.getLogger(__name__)


@dataclass
class _ProcState:
    state: str = "NORMAL"          # "NORMAL" | "THROTTLED"
    consecutive_high: float = 0.0  # seconds spent above threshold
    consecutive_low: float = 0.0   # seconds spent below restore threshold
    original_nice: Optional[int] = None
    throttle_nice: Optional[int] = None
    process_name: str = ""


class ProBalance:
    """Tracks per-process CPU usage and applies/reverts nice throttling."""

    def __init__(self, config: dict, log_callback=None):
        self._cfg = config
        self._log_callback = log_callback
        self._states: dict[ProcessIdentity, _ProcState] = {}

    def update_config(self, config: dict):
        was_enabled = self._cfg.get("enabled", True)
        self._cfg = config
        if was_enabled and not config.get("enabled", True):
            self._restore_all_throttled()
        elif config.get("enabled", True):
            self._restore_exempt_throttled()

    @staticmethod
    def _identity_is_current(identity: ProcessIdentity) -> bool:
        """Return whether PID still names the process that owns this state."""
        # Zero is retained only for legacy/test mappings that lack create_time.
        if identity.create_time == 0.0:
            return True
        try:
            return psutil.Process(identity.pid).create_time() == identity.create_time
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def _restore_all_throttled(self):
        """Restore every process currently throttled by ProBalance."""
        for identity, state in list(self._states.items()):
            if state.state != "THROTTLED":
                continue
            if not self._identity_is_current(identity):
                self._states.pop(identity, None)
                continue

            original_nice = state.original_nice
            if original_nice is None:
                original_nice = 0
            if utils.set_nice(identity.pid, original_nice):
                self._log(
                    f"[ProBalance] RESTORE pid={identity.pid} nice→{original_nice} "
                    "(ProBalance disabled)"
                )
                state.state = "NORMAL"
                state.consecutive_high = 0.0
                state.consecutive_low = 0.0
                state.original_nice = original_nice
                state.throttle_nice = None

    def _restore_exempt_throttled(self):
        """Immediately restore processes newly covered by the exempt list."""
        for identity, state in list(self._states.items()):
            if state.state != "THROTTLED" or not self._is_exempt(state.process_name):
                continue
            if not self._identity_is_current(identity):
                self._states.pop(identity, None)
                continue
            original_nice = state.original_nice if state.original_nice is not None else 0
            if utils.set_nice(identity.pid, original_nice):
                self._log(
                    f"[ProBalance] RESTORE {state.process_name}({identity.pid}) "
                    f"nice→{original_nice} (process exempted)"
                )
                self._states.pop(identity, None)

    def set_log_callback(self, cb):
        self._log_callback = cb

    def forget_pid(self, pid: int):
        """Discard runtime state when a process exits or its PID is reused."""
        self._states = {
            identity: state
            for identity, state in self._states.items()
            if identity.pid != pid
        }

    def _log(self, msg: str):
        log.info(msg)
        if self._log_callback:
            self._log_callback(msg)

    def _is_exempt(self, name: str) -> bool:
        patterns = self._cfg.get("exempt_patterns", [])
        name_lower = name.lower()
        return any(p.lower() in name_lower for p in patterns)

    def tick(
        self,
        snapshot: list[ProcessInfo | ProcessSnapshot | ProcessPolicyView],
        tick_seconds: float,
    ):
        """
        Called every ProBalance update interval.
        snapshot: list of dicts with keys: pid, name, cpu_percent, nice
        tick_seconds: elapsed time since last tick
        """
        if not self._cfg.get("enabled", True):
            # update_config() restores immediately; retry here in case a process
            # temporarily rejected that first attempt.
            alive_identities = {ProcessIdentity.from_record(p) for p in snapshot}
            self._states = {
                identity: state
                for identity, state in self._states.items()
                if identity in alive_identities
            }
            self._restore_all_throttled()
            return

        threshold = self._cfg.get("cpu_threshold_percent", 85.0)
        consec_threshold = self._cfg.get("consecutive_seconds", 3)
        adjustment = self._cfg.get("nice_adjustment", 10)
        nice_floor = self._cfg.get("nice_floor", 15)
        restore_threshold = self._cfg.get("restore_threshold_percent", 40.0)
        restore_hysteresis = self._cfg.get("restore_hysteresis_seconds", 5)

        alive_identities = {ProcessIdentity.from_record(p) for p in snapshot}

        # Clean up dead processes
        dead = [identity for identity in self._states if identity not in alive_identities]
        for identity in dead:
            del self._states[identity]

        for proc in snapshot:
            pid = proc["pid"]
            identity = ProcessIdentity.from_record(proc)
            name = proc["name"]
            cpu = proc.get("cpu_percent", 0.0)
            current_nice = proc.get("nice", 0)

            if pid == os.getpid():
                continue

            if self._is_exempt(name):
                state = self._states.get(identity)
                if state is not None:
                    state.process_name = name
                    if state.state == "THROTTLED":
                        self._restore_exempt_throttled()
                continue

            if identity not in self._states:
                self._states[identity] = _ProcState(
                    original_nice=current_nice,
                    process_name=name,
                )

            state = self._states[identity]
            state.process_name = name

            if state.state == "NORMAL":
                if cpu > threshold:
                    state.consecutive_high += tick_seconds
                    if state.consecutive_high >= consec_threshold:
                        # Throttle
                        new_nice = min(current_nice + adjustment, nice_floor)
                        state.original_nice = current_nice
                        if utils.set_nice(pid, new_nice):
                            state.state = "THROTTLED"
                            state.throttle_nice = new_nice
                            state.consecutive_high = 0.0
                            state.consecutive_low = 0.0
                            self._log(
                                f"[ProBalance] THROTTLE {name}({pid}) "
                                f"cpu={cpu:.1f}% nice {current_nice}→{new_nice}"
                            )
                else:
                    state.consecutive_high = max(0.0, state.consecutive_high - tick_seconds)

            elif state.state == "THROTTLED":
                if cpu < restore_threshold:
                    state.consecutive_low += tick_seconds
                    if state.consecutive_low >= restore_hysteresis:
                        # Restore
                        orig = state.original_nice if state.original_nice is not None else 0
                        if utils.set_nice(pid, orig):
                            self._log(
                                f"[ProBalance] RESTORE {name}({pid}) "
                                f"cpu={cpu:.1f}% nice {current_nice}→{orig}"
                            )
                        state.state = "NORMAL"
                        state.consecutive_high = 0.0
                        state.consecutive_low = 0.0
                        state.original_nice = orig
                        state.throttle_nice = None
                else:
                    state.consecutive_low = 0.0

    def get_throttled_pids(self) -> set[int]:
        return {
            identity.pid
            for identity, state in self._states.items()
            if state.state == "THROTTLED"
        }
