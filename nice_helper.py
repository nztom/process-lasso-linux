"""Privileged negative-nice operations for Process Lasso rules."""
from __future__ import annotations

import logging
import subprocess

import utils

log = logging.getLogger(__name__)

HELPER = "/usr/local/bin/process-lasso-sysfs"


def set_negative_nice_threads(tids: list[int], nice: int) -> set[int]:
    """Privileged backend for the shared niceness write boundary."""
    tids = sorted(set(tids))
    if not tids or any(tid <= 0 for tid in tids) or not -20 <= nice < 0:
        return set()
    try:
        needed = [tid for tid in tids if utils.get_thread_nice(tid) != nice]
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
