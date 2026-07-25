"""MonitorThread: background QThread that scans processes and enforces rules."""
from __future__ import annotations

import os
import pwd
import time
import logging

import psutil
from PyQt6.QtCore import QThread, pyqtSignal

from rules import RuleEngine
from probalance import ProBalance
from process_info import ProcessInfo
import utils

log = logging.getLogger(__name__)


_SUDO_OPTIONS_WITH_VALUE = {
    "-C", "--close-from", "-D", "--chdir", "-g", "--group",
    "-h", "--host", "-p", "--prompt", "-R", "--chroot",
    "-T", "--command-timeout", "-u", "--user",
}


def _resolve_sudo_command(cmdline: list[str]) -> str:
    """Return the command wrapped by sudo, or ``sudo`` if none is visible."""
    args = list(cmdline[1:])
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            i += 1
            break
        if arg in _SUDO_OPTIONS_WITH_VALUE:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        if "=" in arg and not arg.startswith(("/", "./", "../")):
            i += 1
            continue
        break

    # `sudo env KEY=value command` is a common way to pass a custom runtime
    # environment. Show the command rather than the env utility.
    if i < len(args) and os.path.basename(args[i]) == "env":
        i += 1
        while i < len(args) and (args[i].startswith("-") or "=" in args[i]):
            i += 1

    if i >= len(args):
        return "sudo"
    return os.path.basename(args[i].replace("\\", "/")) or "sudo"


def _resolve_name(comm: str, cmdline: list[str]) -> str:
    """Return the best human-readable process name.

    Wine/Proton processes have comm='Main' (or other generic names) but
    cmdline[0] is the Windows path, e.g.:
      Z:\\...\\PathOfExileSteam.exe
    We detect that and use the Windows basename instead.
    Also handles comm truncated at 15 chars by trying cmdline[0] basename.
    """
    if cmdline:
        arg0 = cmdline[0]
        if comm == "sudo" or os.path.basename(arg0) == "sudo":
            return _resolve_sudo_command(cmdline)
        # Windows path: contains backslash and ends with .exe (case-insensitive)
        if "\\" in arg0 and arg0.lower().endswith(".exe"):
            basename = arg0.replace("\\", "/").rstrip("/").split("/")[-1]
            if basename:
                return basename
        # comm is capped at 15 chars by the kernel; if it looks truncated,
        # try to get the real name from the argv[0] basename
        if len(comm) == 15:
            basename = os.path.basename(arg0)
            if basename and len(basename) > 15:
                return basename
    return comm


def _safe_proc_identity(proc: psutil.Process) -> ProcessInfo | None:
    """Collect cacheable process identity fields once per PID."""
    try:
        with proc.oneshot():
            pid = proc.pid
            create_time = proc.create_time()
            comm = proc.name()
            try:
                cmdline = proc.cmdline()
            except (psutil.AccessDenied, psutil.ZombieProcess):
                cmdline = []
            name = _resolve_name(comm, cmdline)
            try:
                username = pwd.getpwuid(proc.uids().effective).pw_name
            except (psutil.AccessDenied, KeyError, AttributeError):
                try:
                    username = proc.username()
                except (psutil.AccessDenied, KeyError):
                    username = ""
            sudo = comm == "sudo" or (
                bool(cmdline) and os.path.basename(cmdline[0]) == "sudo"
            )
            if not sudo:
                try:
                    parent = proc.parent()
                    sudo = parent is not None and parent.name() == "sudo"
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    pass
            try:
                nice = proc.nice()
            except (psutil.AccessDenied, AttributeError):
                nice = 0
            return {
                "pid": pid,
                "create_time": create_time,
                "comm": comm,
                "name": name,
                "user": username,
                "sudo": sudo,
                "cpu_percent": 0.0,
                "mem_rss": 0,
                "nice": nice,
                "affinity": "",
                "ionice": "",
                "cmdline": " ".join(cmdline) if cmdline else "",
            }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def _update_proc_metrics(
    proc: psutil.Process,
    info: ProcessInfo,
    *,
    include_details: bool,
) -> bool:
    """Refresh dynamic fields; expensive display details are optional."""
    try:
        with proc.oneshot():
            info["cpu_percent"] = proc.cpu_percent()
            try:
                info["nice"] = proc.nice()
            except (psutil.AccessDenied, AttributeError):
                pass
            if include_details:
                info["mem_rss"] = proc.memory_info().rss
                try:
                    affinity = proc.cpu_affinity()
                    info["affinity"] = utils._cpuset_to_cpulist(set(affinity))
                except (psutil.AccessDenied, AttributeError):
                    pass
                try:
                    ionice = proc.ionice()
                    info["ionice"] = f"{ionice.ioclass}/{ionice.value}"
                except (psutil.AccessDenied, AttributeError):
                    pass
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def _safe_proc_info(proc: psutil.Process) -> ProcessInfo | None:
    """Collect a complete process record for callers outside the monitor."""
    info = _safe_proc_identity(proc)
    if info is None or not _update_proc_metrics(proc, info, include_details=True):
        return None
    return info


class MonitorThread(QThread):
    """
    Background thread that:
    - Every 0.5s: continues the startup rule burst for new processes
    - Every 1.0s: runs ProBalance tick
    - Every 2.0s: emits process_snapshot_ready with a copy of the snapshot
    - On new PID: applies matching rule, or default affinity if no rule matched
    """

    process_snapshot_ready = pyqtSignal(list)    # emitted with list of proc dicts
    cpu_snapshot_ready     = pyqtSignal(list)    # emitted with list of per-CPU % floats
    log_message = pyqtSignal(str)                # log lines for UI

    def __init__(self, rule_engine: RuleEngine, probalance: ProBalance, config: dict):
        super().__init__()
        self._rule_engine = rule_engine
        self._probalance = probalance
        self._config = config
        self._stop = False
        self._known_pids: set[int] = set()
        self._known_tids_by_pid: dict[int, set[int]] = {}
        self._manually_overridden_pids: set[int] = set()
        self._process_cache: dict[int, ProcessInfo] = {}

        # Track original affinity before we change it, for "Reset All" function.
        # pid → frozenset of CPU numbers that were online when we first touched the process.
        self._original_affinities: dict[int, frozenset] = {}

        # Gaming Mode nice -1 tracking: pid → original nice value before we elevated it
        self._gaming_mode: bool = False
        self._gaming_mode_elevate_nice: bool = False
        self._gaming_niced: dict[int, int] = {}  # pid → original nice

        # Wire log callbacks
        rule_engine.set_log_callback(self._emit_log)
        probalance.set_log_callback(self._emit_log)

    def _emit_log(self, msg: str):
        self.log_message.emit(msg)

    def _default_affinity(self) -> str | None:
        return self._config.get("cpu", {}).get("default_affinity") or None

    def update_config(self, config: dict):
        self._config = config
        self._probalance.update_config(config.get("probalance", {}))

    def reapply_all_defaults(self):
        """Force re-apply default affinity to all currently known PIDs.
        Called when the user changes the default affinity setting."""
        default = self._default_affinity()
        for pid in list(self._known_pids):
            try:
                comm = open(f"/proc/{pid}/comm").read().strip()
                try:
                    cmdline_raw = open(f"/proc/{pid}/cmdline").read().split("\x00")
                except OSError:
                    cmdline_raw = []
                name = _resolve_name(comm, cmdline_raw)
                if self._rule_engine.matches_process(name):
                    self._rule_engine.apply_to_process(pid, name)
                elif default:
                    if utils.set_affinity(pid, default):
                        self._emit_log(f"[Default] affinity={default} → {name}({pid})")
            except OSError:
                pass

    def set_gaming_mode(self, active: bool, elevate_nice: bool):
        """Called from GUI thread when Gaming Mode is toggled.
        If deactivating, restores nice values for all processes we elevated."""
        self._gaming_mode = active
        self._gaming_mode_elevate_nice = elevate_nice
        if not active and self._gaming_niced:
            self._restore_gaming_nices()

    def _restore_gaming_nices(self):
        """Restore nice values to original for all game processes we elevated."""
        import cpu_park
        count = 0
        for pid, orig_nice in list(self._gaming_niced.items()):
            try:
                if cpu_park.set_process_nice_via_helper(pid, orig_nice):
                    count += 1
            except Exception:
                pass
        self._gaming_niced.clear()
        self._emit_log(f"[Gaming Mode] Restored nice for {count} processes.")

    def set_manual_rule_override(self, pid: int):
        """Stop the startup burst after a manual affinity or nice change."""
        self._manually_overridden_pids.add(pid)
        self._rule_engine.suppress_pid(pid)

    def stop(self):
        self._rule_engine.flush_priority_state()
        self._stop = True

    def reset_all_affinities(self):
        """Restore every process we touched back to its original affinity.
        Called by the GUI 'Reset All Changes' button.
        Processes that have since exited are silently skipped."""
        online = utils.get_cpu_count()
        all_cpus = set(range(online))
        count = 0
        for pid, orig in list(self._original_affinities.items()):
            try:
                # Restore to captured original; fall back to all CPUs
                mask = orig if orig else all_cpus
                os.sched_setaffinity(pid, mask)
                # Restore all threads too
                for tid in utils.get_process_tids(pid):
                    try:
                        os.sched_setaffinity(tid, mask)
                    except OSError:
                        pass
                count += 1
            except (ProcessLookupError, PermissionError, OSError):
                pass
        self._original_affinities.clear()
        self._emit_log(f"[Reset] Restored affinity on {count} processes to original state.")

    def _capture_original(self, pid: int):
        """Store the current affinity of a process before we change it."""
        if pid in self._original_affinities:
            return
        try:
            self._original_affinities[pid] = frozenset(os.sched_getaffinity(pid))
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _forget_process(self, pid: int):
        """Clear all runtime state associated with one process identity."""
        self._rule_engine.forget_pid(pid)
        self._probalance.forget_pid(pid)
        self._process_cache.pop(pid, None)
        self._original_affinities.pop(pid, None)
        self._gaming_niced.pop(pid, None)
        self._known_tids_by_pid.pop(pid, None)
        self._manually_overridden_pids.discard(pid)

    def _snapshot_records(self) -> list[ProcessInfo]:
        """Return records detached from the worker-owned mutable cache."""
        return [dict(info) for info in self._process_cache.values()]

    def _apply_new_pid(self, info: ProcessInfo):
        """Apply rules or default affinity to a newly seen process."""
        pid = info["pid"]
        name = info["name"]
        self._known_tids_by_pid.setdefault(pid, set(utils.get_process_tids(pid)))
        self._capture_original(pid)
        matched = self._rule_engine.matches_process(name)
        if matched:
            self._rule_engine.apply_to_process(pid, name)
            # Rule matched — if gaming mode + elevate_nice, apply nice -1
            if self._gaming_mode and self._gaming_mode_elevate_nice and pid not in self._gaming_niced:
                import cpu_park
                orig_nice = info.get("nice", 0)
                if cpu_park.set_process_nice_via_helper(pid, -1):
                    self._gaming_niced[pid] = orig_nice
                    self._emit_log(f"[Gaming Mode] nice -1 → {name}({pid})")
        else:
            default = self._default_affinity()
            if default:
                if utils.set_affinity(pid, default):
                    self._emit_log(f"[Default] affinity={default} → {name}({pid})")

    def _sync_new_threads(self):
        """Apply process rules to TIDs first observed after process startup."""
        default = self._default_affinity()
        for pid, info in list(self._process_cache.items()):
            current_tids = set(utils.get_process_tids(pid))
            if not current_tids:
                continue
            known_tids = self._known_tids_by_pid.setdefault(pid, set())
            new_tids = current_tids - known_tids
            for tid in sorted(new_tids):
                if self._rule_engine.matches_process(info["name"]):
                    self._rule_engine.apply_to_thread(pid, tid, info["name"])
                elif (
                    default
                    and pid not in self._manually_overridden_pids
                    and utils.set_thread_affinity(tid, default)
                ):
                    self._emit_log(
                        f"[Default] affinity={default} → new thread "
                        f"{info['name']}({tid})"
                    )
            self._known_tids_by_pid[pid] = current_tids

    def _sync_processes(self, procs: list[psutil.Process]) -> dict[int, psutil.Process]:
        """Update the PID set and cache identities only for new/changed PIDs."""
        by_pid = {proc.pid: proc for proc in procs}
        current_pids = set(by_pid)
        new_pids = current_pids - self._known_pids
        exited_pids = self._known_pids - current_pids

        for pid in new_pids:
            info = _safe_proc_identity(by_pid[pid])
            if info is not None:
                self._process_cache[pid] = info
                self._apply_new_pid(info)

        # A process can exec into a different program without changing PID.
        # Checking only the cheap comm field keeps rule names correct without
        # rebuilding every process's full metadata on each enforcement pass.
        for pid in current_pids - new_pids:
            info = self._process_cache.get(pid)
            if info is None:
                refreshed = _safe_proc_identity(by_pid[pid])
                if refreshed is not None:
                    self._process_cache[pid] = refreshed
                    self._apply_new_pid(refreshed)
                continue
            try:
                pid_reused = by_pid[pid].create_time() != info.get("create_time")
                command_changed = by_pid[pid].name() != info.get("comm")
                if pid_reused:
                    self._forget_process(pid)
                if pid_reused or command_changed:
                    refreshed = _safe_proc_identity(by_pid[pid])
                    if refreshed is not None:
                        self._process_cache[pid] = refreshed
                        self._apply_new_pid(refreshed)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        for pid in exited_pids:
            self._forget_process(pid)

        self._known_pids = current_pids
        return by_pid

    def run(self):
        tick_interval = 0.1
        last_enforce = 0.0
        last_probalance = 0.0
        last_snapshot = 0.0
        last_pb_tick = time.monotonic()

        enforce_interval = self._config.get("monitor", {}).get("rule_enforce_interval_ms", 500) / 1000.0
        snapshot_interval = self._config.get("monitor", {}).get("display_refresh_interval_ms", 2000) / 1000.0

        snapshot: list[dict] = []

        while not self._stop:
          try:
            now = time.monotonic()

            elapsed_enforce = now - last_enforce
            elapsed_pb = now - last_probalance
            elapsed_snap = now - last_snapshot

            enforce_due = elapsed_enforce >= enforce_interval
            pb_due = elapsed_pb >= 1.0
            snapshot_due = elapsed_snap >= snapshot_interval

            if not (enforce_due or pb_due or snapshot_due):
                time.sleep(tick_interval)
                continue

            try:
                procs = list(psutil.process_iter())
            except Exception:
                procs = []
            by_pid = self._sync_processes(procs)

            # Give newly seen matching processes a short rule burst.
            if enforce_due:
                for info in self._process_cache.values():
                    self._rule_engine.apply_to_process(info["pid"], info["name"])
                self._sync_new_threads()
                last_enforce = now

            # Refresh CPU/nice only when ProBalance or the display needs them.
            if pb_due or snapshot_due:
                for pid, info in list(self._process_cache.items()):
                    proc = by_pid.get(pid)
                    if proc is not None:
                        _update_proc_metrics(proc, info, include_details=snapshot_due)
            # The GUI receives these across a queued signal. Copy nested
            # records so later worker updates cannot mutate UI-owned data.
            snapshot = self._snapshot_records()

            # ProBalance every 1.0s
            if pb_due:
                pb_tick = now - last_pb_tick
                last_pb_tick = now
                self._probalance.tick(
                    [info for info in snapshot if info["pid"] != os.getpid()],
                    pb_tick,
                )
                last_probalance = now

            # Snapshot emit every 2.0s
            if snapshot_due:
                self.process_snapshot_ready.emit(list(snapshot))
                try:
                    raw = psutil.cpu_percent(percpu=True)
                    # psutil returns only ONLINE CPUs in cpu-number order.
                    # When Gaming Mode parks a CCD the list is shorter and
                    # the indices no longer match CPU numbers.
                    # Build a full-length list indexed by actual CPU number.
                    online = sorted(utils.get_online_cpus())
                    total  = utils.get_cpu_count()
                    full   = [0.0] * total
                    for idx, cpu_num in enumerate(online):
                        if idx < len(raw) and cpu_num < total:
                            full[cpu_num] = raw[idx]
                    self.cpu_snapshot_ready.emit(full)
                except Exception:
                    pass
                last_snapshot = now

            time.sleep(tick_interval)
          except Exception as exc:
            log.exception("MonitorThread: unexpected error in main loop: %s", exc)
            time.sleep(1.0)  # brief back-off to avoid busy-spinning on persistent errors
