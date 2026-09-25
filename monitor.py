"""Background process scanner and persistent-policy enforcer."""
from __future__ import annotations

import os
import pwd
import time
import logging
import threading

import psutil
from PyQt6.QtCore import QThread, pyqtSignal

from rules import RuleEngine
from probalance import ProBalance
from process_info import ProcessInfo, ProcessPolicyView, ProcessSnapshot
from runtime_cleanup import ProcessRuntimeCleanup
from gpu_memory import NvidiaGpuMemorySampler
import config as config_module
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
                "gpu_percent": 0.0,
                "gpu_mem": 0,
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
        prefetched = proc.info if isinstance(getattr(proc, "info", None), dict) else {}
        with proc.oneshot():
            cpu_percent = prefetched.get("cpu_percent")
            info["cpu_percent"] = (
                proc.cpu_percent() if cpu_percent is None else cpu_percent
            )
            nice = prefetched.get("nice")
            if nice is not None:
                info["nice"] = nice
            else:
                try:
                    info["nice"] = proc.nice()
                except (psutil.AccessDenied, AttributeError):
                    pass
            if include_details:
                memory_info = prefetched.get("memory_info")
                info["mem_rss"] = (
                    proc.memory_info().rss
                    if memory_info is None else memory_info.rss
                )
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
    Run discovery, persistent policies, ProBalance, metrics, and snapshots on
    the configured global monitor interval.
    """

    process_snapshot_ready = pyqtSignal(list)    # list[ProcessPolicyView]
    cpu_snapshot_ready     = pyqtSignal(list)    # emitted with list of per-CPU % floats
    log_message = pyqtSignal(str)                # log lines for UI

    def __init__(self, rule_engine: RuleEngine, probalance: ProBalance, config: dict,
                 game_sessions=None):
        super().__init__()
        self._rule_engine = rule_engine
        self._probalance = probalance
        self._config = config
        self._game_sessions = game_sessions
        self._game_memberships = {}
        self._stop = False
        self._wake_event = threading.Event()
        self._known_pids: set[int] = set()
        self._known_tids_by_pid: dict[int, set[int]] = {}
        self._manually_overridden_pids: set[int] = set()
        self._manual_overrides_by_pid: dict[int, set[str]] = {}
        self._process_cache: dict[int, ProcessInfo] = {}
        self._gpu_memory = NvidiaGpuMemorySampler()

        # Track original affinity before we change it for internal restoration.
        # pid → frozenset of CPU numbers that were online when we first touched the process.
        self._original_affinities: dict[int, frozenset] = {}

        self._runtime_cleanup = ProcessRuntimeCleanup(
            rule_engine,
            probalance,
            self._forget_monitor_state,
        )

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
        # Interrupt the current wait so a new global interval takes effect now.
        self._wake_event.set()

    def reapply_all_defaults(self):
        """Reapply saved rules and eligible default affinity to known PIDs.

        Default affinity coexists with saved non-affinity policies, but yields
        to an Always affinity policy and does not alter active game sessions.
        Called when the user changes the default affinity setting.
        """
        default = self._default_affinity()
        for pid in list(self._known_pids):
            try:
                comm = open(f"/proc/{pid}/comm").read().strip()
                try:
                    cmdline_raw = open(f"/proc/{pid}/cmdline").read().split("\x00")
                except OSError:
                    cmdline_raw = []
                name = _resolve_name(comm, cmdline_raw)
                matched = self._rule_engine.matches_process(name)
                policy = self._rule_engine.effective_policy(name)
                if matched:
                    self._rule_engine.apply_to_process(pid, name)
                if default and policy.affinity is None:
                    if (self._game_sessions and self._game_sessions.session_for_pid(pid)):
                        continue
                    if utils.set_affinity(pid, default):
                        self._emit_log(f"[Default] affinity={default} → {name}({pid})")
            except OSError:
                pass

    def set_manual_policy_override(self, pid: int, policy: str | None = None):
        """Preserve a manual change without disabling unrelated policies."""
        self._manually_overridden_pids.add(pid)
        marker = "*" if policy is None else policy
        self._manual_overrides_by_pid.setdefault(pid, set()).add(marker)
        self._rule_engine.suppress_pid(pid, policy)

    def _affinity_manually_overridden(self, pid: int) -> bool:
        fields = self._manual_overrides_by_pid.get(pid)
        if fields is None:
            return pid in self._manually_overridden_pids
        return bool({"*", "affinity"} & fields)

    def stop(self):
        self._rule_engine.flush_priority_state()
        self._stop = True
        self._wake_event.set()

    def _monitor_interval(self) -> float:
        """Return the current global monitor cadence in seconds."""
        return max(
            0.001,
            config_module.monitor_interval_ms(self._config) / 1000.0,
        )

    def _wait_for_wake(self, timeout: float):
        """Wait interruptibly for shutdown or a saved configuration change."""
        self._wake_event.wait(timeout)
        self._wake_event.clear()

    def reset_all_affinities(self):
        """Restore every process we touched back to its original affinity.
        Available for controlled shutdown or future administrative workflows.
        Processes that have since exited are silently skipped."""
        all_cpus = utils.get_online_cpus()
        count = 0
        for pid, orig in list(self._original_affinities.items()):
            # Restore to captured original; fall back to all online CPUs.
            mask = set(orig) if orig else all_cpus
            if utils.set_process_affinity_set(pid, mask):
                count += 1
        self._original_affinities.clear()
        self._emit_log(f"[Reset] Restored affinity on {count} processes to original state.")

    def _capture_original(self, pid: int):
        """Store the current affinity of a process before we change it."""
        if pid in self._original_affinities:
            return
        affinity = utils.get_thread_affinity_set(pid)
        if affinity is not None:
            self._original_affinities[pid] = frozenset(affinity)

    def _forget_monitor_state(self, pid: int):
        """Clear Monitor-owned state for one ended process identity."""
        self._process_cache.pop(pid, None)
        self._original_affinities.pop(pid, None)
        self._known_tids_by_pid.pop(pid, None)
        self._manually_overridden_pids.discard(pid)
        self._manual_overrides_by_pid.pop(pid, None)

    def _forget_process(self, pid: int):
        """Coordinate cleanup after process exit or detected PID reuse."""
        self._runtime_cleanup.forget_pid(pid)

    def _observed_records(self) -> list[ProcessSnapshot]:
        """Detach immutable observations from the worker-owned cache."""
        return [
            ProcessSnapshot.from_info(info)
            for info in self._process_cache.values()
        ]

    def _snapshot_records(
        self, observed_records: list[ProcessSnapshot] | None = None
    ) -> list[ProcessPolicyView]:
        """Join detached observations with policy once per display snapshot."""
        views = []
        for observed in observed_records or self._observed_records():
            views.append(ProcessPolicyView(
                observed=observed,
                effective_policy=self._rule_engine.effective_policy(observed.name),
                manually_overridden=observed.pid in self._manually_overridden_pids,
                game_id=(self._game_memberships.get((observed.pid, observed.create_time)) or {}).get("game_id"),
                game_name=(self._game_memberships.get((observed.pid, observed.create_time)) or {}).get("game_name"),
            ))
        return views

    def _apply_new_pid(self, info: ProcessInfo):
        """Apply saved fields, plus default affinity when no affinity rule wins."""
        pid = info["pid"]
        name = info["name"]
        self._known_tids_by_pid.setdefault(pid, set(utils.get_process_tids(pid)))
        self._capture_original(pid)
        game_session = (self._game_sessions.session_for_pid(
            pid, float(info.get("create_time", 0.0))) if self._game_sessions else None)
        if game_session and not self._game_sessions.launch_has_started(game_session, pid, name):
            return
        matched = self._rule_engine.matches_process(name)
        policy = self._rule_engine.effective_policy(name)
        if matched:
            self._rule_engine.apply_to_process(pid, name)
        if policy.affinity is None and not game_session:
            default = self._default_affinity()
            if default:
                if utils.set_affinity(pid, default):
                    self._emit_log(f"[Default] affinity={default} → {name}({pid})")

    def _policies_ready(self, info) -> bool:
        if not self._game_sessions:
            return True
        session = self._game_sessions.session_for_pid(
            int(info["pid"]), float(info.get("create_time", 0.0)))
        return not session or self._game_sessions.launch_has_started(
            session, int(info["pid"]), str(info["name"]))

    def _sync_new_threads(self):
        """Apply saved fields and eligible default affinity to newly seen TIDs."""
        default = self._default_affinity()
        for pid, info in list(self._process_cache.items()):
            matched = self._rule_engine.matches_process(info["name"])
            policy = self._rule_engine.effective_policy(info["name"])
            if not matched and not default:
                continue
            current_tids = set(utils.get_process_tids(pid))
            if not current_tids:
                continue
            known_tids = self._known_tids_by_pid.setdefault(pid, set())
            new_tids = current_tids - known_tids
            for tid in sorted(new_tids):
                if not self._policies_ready(info):
                    continue
                if matched:
                    self._rule_engine.apply_to_thread(pid, tid, info["name"])
                if (
                    default
                    and policy.affinity is None
                    and not self._affinity_manually_overridden(pid)
                    and not (self._game_sessions and self._game_sessions.session_for_pid(pid))
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
                # Both values come from /proc/<pid>/stat on Linux.  oneshot()
                # lets psutil share that read instead of doing it twice for
                # every process on every enforcement pass.
                prefetched = (
                    by_pid[pid].info
                    if isinstance(getattr(by_pid[pid], "info", None), dict)
                    else {}
                )
                with by_pid[pid].oneshot():
                    create_time = prefetched.get("create_time")
                    if create_time is None:
                        create_time = by_pid[pid].create_time()
                    comm = prefetched.get("name")
                    if comm is None:
                        comm = by_pid[pid].name()
                    pid_reused = (
                        create_time != info.get("create_time")
                    )
                    command_changed = comm != info.get("comm")
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
        last_monitor = 0.0
        last_pb_tick = time.monotonic()

        snapshot: list[ProcessSnapshot] = []

        while not self._stop:
          try:
            # update_config() wakes this loop, so saved values replace the old
            # cadence without waiting for the previous interval to expire.
            monitor_interval = self._monitor_interval()
            now = time.monotonic()
            elapsed = now - last_monitor
            if elapsed < monitor_interval:
                self._wait_for_wake(monitor_interval - elapsed)
                continue

            try:
                # psutil collects these fields under one per-process oneshot
                # cache, shared by identity synchronization and metric sampling.
                procs = list(psutil.process_iter(attrs=[
                    "pid", "name", "create_time", "cpu_percent", "nice",
                    "memory_info",
                ], ad_value=None))
            except Exception:
                procs = []
            by_pid = self._sync_processes(procs)
            if self._game_sessions and self._game_sessions.sessions:
                self._game_memberships = self._game_sessions.refresh(
                    self._observed_records()
                )

            for info in self._process_cache.values():
                if self._policies_ready(info):
                    self._rule_engine.apply_to_process(info["pid"], info["name"])
            self._sync_new_threads()

            for pid, info in list(self._process_cache.items()):
                proc = by_pid.get(pid)
                if proc is not None:
                    _update_proc_metrics(proc, info, include_details=True)
            gpu_percent, gpu_memory = self._gpu_memory.sample()
            for pid, info in self._process_cache.items():
                info["gpu_percent"] = gpu_percent.get(pid, 0.0)
                info["gpu_mem"] = gpu_memory.get(pid, 0)
            snapshot = self._observed_records()

            pb_tick = now - last_pb_tick
            last_pb_tick = now
            self._probalance.tick(
                [info for info in snapshot
                 if info["pid"] != os.getpid() and
                 (info.pid, info.create_time) not in self._game_memberships],
                pb_tick,
            )

            views = self._snapshot_records(snapshot)
            self.process_snapshot_ready.emit(views)
            try:
                raw = psutil.cpu_percent(percpu=True)
                # psutil returns only ONLINE CPUs in cpu-number order.
                # When CPUs are offline the list is shorter and
                # the indices no longer match CPU numbers.
                # Build a full-length list indexed by actual CPU number.
                import cpu_tools
                cpu_info = cpu_tools.get_cpu_info()
                online = sorted(cpu_info.online)
                total = cpu_info.cpu_count
                full = [0.0] * total
                for idx, cpu_num in enumerate(online):
                    if idx < len(raw) and cpu_num < total:
                        full[cpu_num] = raw[idx]
                self.cpu_snapshot_ready.emit(full)
            except Exception:
                pass
            last_monitor = now
          except Exception as exc:
            log.exception("MonitorThread: unexpected error in main loop: %s", exc)
            # Keep error back-off interruptible for shutdown and settings saves.
            self._wait_for_wake(1.0)
        self._gpu_memory.close()
