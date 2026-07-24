"""Privileged negative-nice operations for Process Lasso rules."""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

HELPER = "/usr/local/bin/process-lasso-sysfs"


def set_negative_nice(pid: int, nice: int) -> bool:
    """Set a negative nice value through the installed sudo helper."""
    if pid <= 0 or not -20 <= nice < 0:
        log.warning("invalid privileged renice request: pid=%d nice=%d", pid, nice)
        return False

    try:
        result = subprocess.run(
            ["sudo", HELPER, "renice-pid", str(nice), str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        log.warning("privileged renice pid=%d nice=%d failed: %s", pid, nice, exc)
        return False

    if result.returncode == 0:
        return True

    message = (result.stderr or result.stdout).strip()
    log.warning("privileged renice pid=%d nice=%d failed: %s", pid, nice, message)
    return False
