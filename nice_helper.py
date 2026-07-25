"""Privileged negative-nice operations for Process Lasso rules."""
from __future__ import annotations

import logging
import os
import subprocess

import utils

log = logging.getLogger(__name__)

HELPER = "/usr/local/bin/process-lasso-sysfs"


def set_negative_nice(pid: int, nice: int) -> bool:
    """Set a negative nice value on every thread in a process."""
    if pid <= 0 or not -20 <= nice < 0:
        log.warning("invalid privileged renice request: pid=%d nice=%d", pid, nice)
        return False

    tids = utils.get_process_tids(pid)
    if not tids:
        return False

    return bool(set_negative_nice_threads(tids, nice))


def set_negative_nice_threads(tids: list[int], nice: int) -> set[int]:
    """Set one negative nice target on a batch of threads."""
    tids = sorted(set(tids))
    if not tids or any(tid <= 0 for tid in tids) or not -20 <= nice < 0:
        return set()
    try:
        needed = [tid for tid in tids if os.getpriority(os.PRIO_PROCESS, tid) != nice]
        if not needed:
            return set(tids)
        result = subprocess.run(
            ["sudo", HELPER, "renice-pids", str(nice), *map(str, needed)],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, ProcessLookupError, OSError) as exc:
        log.warning("privileged batch renice nice=%d failed: %s", nice, exc)
        return set()
    if result.returncode == 0:
        return set(tids)
    log.warning("privileged batch renice nice=%d failed: %s", nice,
                (result.stderr or result.stdout).strip())
    return set()


def set_negative_nice_thread(tid: int, nice: int) -> bool:
    """Set a negative nice value on one thread."""
    if tid <= 0 or not -20 <= nice < 0:
        log.warning("invalid privileged renice request: tid=%d nice=%d", tid, nice)
        return False
    return tid in set_negative_nice_threads([tid], nice)
