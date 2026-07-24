"""Privileged negative-nice operations for Process Lasso rules."""
from __future__ import annotations

import logging
import os
import subprocess

log = logging.getLogger(__name__)

HELPER = "/usr/local/bin/process-lasso-sysfs"


def _get_tids(pid: int) -> list[int]:
    try:
        return [int(tid) for tid in os.listdir(f"/proc/{pid}/task")]
    except OSError:
        return []


def set_negative_nice(pid: int, nice: int) -> bool:
    """Set a negative nice value on every thread in a process."""
    if pid <= 0 or not -20 <= nice < 0:
        log.warning("invalid privileged renice request: pid=%d nice=%d", pid, nice)
        return False

    tids = _get_tids(pid)
    if not tids:
        return False

    any_ok = False
    for tid in tids:
        try:
            # Avoid another sudo process on later burst passes when this
            # thread already has the requested value.
            if os.getpriority(os.PRIO_PROCESS, tid) == nice:
                any_ok = True
                continue
            result = subprocess.run(
                ["sudo", HELPER, "renice-pid", str(nice), str(tid)],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, ProcessLookupError, OSError) as exc:
            log.warning("privileged renice tid=%d nice=%d failed: %s", tid, nice, exc)
            continue

        if result.returncode == 0:
            any_ok = True
            continue

        message = (result.stderr or result.stdout).strip()
        log.warning("privileged renice tid=%d nice=%d failed: %s", tid, nice, message)
    return any_ok
