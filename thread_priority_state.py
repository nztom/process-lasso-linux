"""Persistent identities and original nice values for offset priority rules."""
from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from pathlib import Path


DEFAULT_STATE_FILE = (
    Path.home() / ".local" / "state" / "process-lasso" /
    "thread-priority-state.json"
)


def read_boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"


def parse_proc_stat_start_time(text: str) -> int:
    """Return field 22 from proc stat, allowing spaces and ')' in comm."""
    end = text.rfind(")")
    if end < 0:
        raise ValueError("invalid proc stat")
    fields_after_comm = text[end + 1 :].split()
    # The first item is field 3 (state), therefore starttime/field 22 is 19.
    if len(fields_after_comm) <= 19:
        raise ValueError("truncated proc stat")
    return int(fields_after_comm[19])


def thread_identity(pid: int, tid: int, rule_id: str, boot_id: str) -> str:
    process_stat = Path(f"/proc/{pid}/stat").read_text()
    thread_stat = Path(f"/proc/{pid}/task/{tid}/stat").read_text()
    return ":".join((
        boot_id,
        str(pid),
        str(parse_proc_stat_start_time(process_stat)),
        str(tid),
        str(parse_proc_stat_start_time(thread_stat)),
        rule_id,
    ))


class ThreadPriorityState:
    """Crash-safe, write-debounced offset priority ledger."""

    def __init__(self, path: Path | None = None, debounce_seconds: float = 0.75):
        self.path = path or DEFAULT_STATE_FILE
        self.boot_id = read_boot_id()
        self.debounce_seconds = debounce_seconds
        self.entries: dict[str, dict] = {}
        self._dirty = False
        self._deadline: float | None = None
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            if data.get("boot_id") == self.boot_id:
                self.entries = dict(data.get("entries", {}))
        except (OSError, ValueError, TypeError):
            self.entries = {}

    def get(self, key: str) -> dict | None:
        return self.entries.get(key)

    def original_for_identity(self, key: str) -> int | None:
        """Find a baseline recorded by any rule for this exact thread identity."""
        identity, separator, _rule_id = key.rpartition(":")
        if not separator:
            return None
        prefix = identity + ":"
        for existing_key, entry in self.entries.items():
            if existing_key.startswith(prefix) and "original_nice" in entry:
                return int(entry["original_nice"])
        return None

    def replace_original_for_identity(self, key: str, original: int) -> bool:
        """Replace all rule-specific baselines for one exact live thread."""
        identity, separator, _rule_id = key.rpartition(":")
        if not separator:
            return False
        changed = False
        prefix = identity + ":"
        for existing_key, entry in self.entries.items():
            if (existing_key.startswith(prefix)
                    and entry.get("original_nice") != original):
                entry["original_nice"] = original
                changed = True
        return changed

    def inferred_original_for_process_target(self, key: str, observed: int) -> int | None:
        """Map an inherited applied target back to its process-local original."""
        parts = key.split(":", 5)
        if len(parts) != 6:
            return None
        boot_id, pid, process_start, _tid, _thread_start, rule_id = parts
        candidates: list[tuple[int, bool]] = []
        for existing_key, entry in self.entries.items():
            existing = existing_key.split(":", 5)
            if len(existing) != 6:
                continue
            e_boot, e_pid, e_process_start, e_tid, _e_start, e_rule = existing
            if ((e_boot, e_pid, e_process_start, e_rule)
                    != (boot_id, pid, process_start, rule_id)):
                continue
            if entry.get("status") != "applied" or entry.get("target_nice") != observed:
                continue
            if "original_nice" in entry:
                candidates.append((int(entry["original_nice"]), e_tid == pid))
        if not candidates:
            return None
        counts = Counter(original for original, _leader in candidates)
        highest = max(counts.values())
        winners = {original for original, count in counts.items() if count == highest}
        if len(winners) == 1:
            return next(iter(winners))
        leader_originals = {
            original for original, is_leader in candidates
            if is_leader and original in winners
        }
        return next(iter(leader_originals)) if len(leader_originals) == 1 else None

    def set_pending(self, key: str, entry: dict) -> None:
        """Persist intent before niceness changes so a crash cannot compound."""
        with self._lock:
            self.entries[key] = {**entry, "status": "pending"}
            self._write()

    def set_pending_many(self, entries: dict[str, dict]) -> None:
        """Persist a startup batch in one atomic replacement."""
        if not entries:
            return
        with self._lock:
            for key, entry in entries.items():
                self.entries[key] = {**entry, "status": "pending"}
            self._write()

    def set_applied(self, key: str, target: int) -> None:
        with self._lock:
            entry = self.entries.get(key)
            if entry is None:
                return
            entry["target_nice"] = target
            entry["status"] = "applied"
            self._mark_dirty()

    def set_failed(self, key: str) -> None:
        with self._lock:
            entry = self.entries.get(key)
            if entry is not None:
                entry["status"] = "failed"
                self._mark_dirty()

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._deadline = time.monotonic() + self.debounce_seconds

    def flush_if_due(self, now: float | None = None) -> bool:
        with self._lock:
            if not self._dirty or self._deadline is None:
                return False
            if (time.monotonic() if now is None else now) < self._deadline:
                return False
            self._write()
            return True

    def flush(self) -> None:
        with self._lock:
            if self._dirty:
                self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(tmp, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump({"boot_id": self.boot_id, "entries": self.entries}, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        os.chmod(self.path, 0o600)
        try:
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
        self._dirty = False
        self._deadline = None

    def prune(self) -> int:
        """Remove entries whose exact process/thread identities no longer exist."""
        removed = 0
        for key in list(self.entries):
            parts = key.split(":", 5)
            if len(parts) != 6:
                del self.entries[key]
                removed += 1
                continue
            boot_id, pid_s, proc_start, tid_s, tid_start, _rule_id = parts
            try:
                if boot_id != self.boot_id:
                    raise OSError
                pid, tid = int(pid_s), int(tid_s)
                if str(parse_proc_stat_start_time(Path(f"/proc/{pid}/stat").read_text())) != proc_start:
                    raise OSError
                if str(parse_proc_stat_start_time(Path(f"/proc/{pid}/task/{tid}/stat").read_text())) != tid_start:
                    raise OSError
            except (OSError, ValueError):
                del self.entries[key]
                removed += 1
        if removed:
            self._mark_dirty()
        return removed
