"""Game Mode launch sessions, runtime persistence, and local IPC."""
from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
import uuid
from pathlib import Path

import cpu_tools
from game_identity import GameCatalog, effective_policy
import utils

MARKER_ENV = "PROCESS_LASSO_GAME_SESSION"
SOCKET_NAME = "process-lasso-game.sock"
STATE_NAME = "process-lasso-game-sessions.json"


def runtime_dir() -> Path:
    path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    if not path.is_dir():
        path = Path("/tmp") / f"process-lasso-{os.getuid()}"
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def socket_path() -> Path:
    return runtime_dir() / SOCKET_NAME


def apply_launch_policy(pid: int, policy: dict) -> list[str]:
    """Apply the shared launch policy and return non-fatal diagnostics."""
    errors = []
    affinity = policy.get("affinity")
    if affinity and not utils.set_affinity(pid, affinity):
        errors.append(f"could not apply affinity {affinity}")
    nice = policy.get("nice")
    if nice is not None:
        if isinstance(nice, int):
            target = nice
        elif nice.get("type", "absolute") == "offset":
            current = os.getpriority(os.PRIO_PROCESS, pid)
            target = max(int(nice.get("floor", -15)), min(
                int(nice.get("ceiling", 19)), current + int(nice["offset"])))
        else:
            target = int(nice["value"])
        if not utils.set_nice(pid, target):
            errors.append(f"could not apply nice {target}")
    return errors


class GameSessionManager:
    def __init__(self, config: dict, log_callback=None, save_callback=None):
        self.config = config
        self._log = log_callback or (lambda _msg: None)
        self._save_config = save_callback or (lambda: None)
        self.sessions: dict[str, dict] = {}
        self._saved_ccd: str | None = None
        self._active_ccd: str | None = None
        self._load_state()

    @property
    def state_path(self):
        return runtime_dir() / STATE_NAME

    def _persist(self):
        data = {"saved_ccd": self._saved_ccd, "sessions": list(self.sessions.values())}
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(self.state_path)

    def _load_state(self):
        try:
            data = json.loads(self.state_path.read_text())
            self._saved_ccd = data.get("saved_ccd")
            for session in data.get("sessions", []):
                pid = int(session["root_pid"])
                token = session["token"]
                marker_alive = any(
                    _process_marker(int(entry.name)) == token
                    for entry in Path("/proc").glob("[0-9]*")
                )
                if _pid_matches(pid, float(session["root_start_time"])) or marker_alive:
                    self.sessions[session["token"]] = session
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if not self.sessions and self._saved_ccd:
            self._restore_ccd()
        elif self.sessions:
            self._active_ccd = self.config.get("game_mode", {}).get("ccd_preference", "cache")

    def activate(self, request: dict) -> dict:
        game_cfg = self.config.setdefault("game_mode", {})
        identity, warning = GameCatalog(game_cfg).resolve(
            list(request.get("argv", [])), dict(request.get("environment", {})),
            request.get("profile"),
        )
        if warning:
            self._log(f"[Game Mode] {warning}; using defaults")
        policy = effective_policy(game_cfg, identity)
        token = str(uuid.uuid4())
        session = {
            "token": token, "root_pid": int(request["pid"]),
            "root_start_time": float(request["start_time"]),
            "game_id": identity.game_id if identity else None,
            "game_name": identity.name if identity else "Game",
            "policy": policy, "argv": list(request.get("argv", [])),
            "created": time.time(),
        }
        if not self.sessions:
            self._activate_ccd(game_cfg.get("ccd_preference", "cache"))
        self.sessions[token] = session
        self._persist()
        self._save_config()
        self._log(f"[Game Mode] Activated {session['game_name']} ({token[:8]})")
        return {"ok": True, "token": token, "game_id": session["game_id"],
                "game_name": session["game_name"], "policy": policy}

    def _activate_ccd(self, preference):
        if not preference:
            return
        if not cpu_tools.get_cpu_info().features.x3d_mode_control:
            self._log("[Game Mode] AMD X3D scheduler preference unavailable")
            return
        current = cpu_tools.get_x3d_mode()
        if current is None:
            self._log("[Game Mode] AMD X3D scheduler preference unavailable")
            return
        self._saved_ccd = current
        ok, message = cpu_tools.set_x3d_mode(preference)
        if not ok:
            self._log(f"[Game Mode] X3D activation failed: {message}")
        else:
            self._active_ccd = preference

    def set_ccd_preference(self, preference):
        """Change Game Mode's preference without losing the saved global mode."""
        self.config.setdefault("game_mode", {})["ccd_preference"] = preference
        if self.sessions:
            if preference:
                ok, message = cpu_tools.set_x3d_mode(preference)
                if ok:
                    self._active_ccd = preference
                else:
                    self._log(f"[Game Mode] X3D preference change failed: {message}")
            else:
                if self._saved_ccd:
                    ok, message = cpu_tools.set_x3d_mode(self._saved_ccd)
                    if not ok:
                        self._log(f"[Game Mode] X3D restore failed: {message}")
                self._saved_ccd = None
                self._active_ccd = None
            self._persist()

    def _restore_ccd(self):
        if self._saved_ccd:
            ok, message = cpu_tools.set_x3d_mode(self._saved_ccd)
            if not ok:
                self._log(f"[Game Mode] X3D restore failed: {message}")
        self._saved_ccd = None
        self._active_ccd = None
        try:
            self.state_path.unlink()
        except FileNotFoundError:
            pass

    def refresh(self, process_records) -> dict[tuple[int, float], dict]:
        """Return current process identities mapped to their game session."""
        records = list(process_records)
        # If another UI changes the global kernel preference while games are
        # active, remember it as the new restoration target and keep the Game
        # Mode preference active until the last session exits.
        if self.sessions and self._active_ccd:
            current = cpu_tools.get_x3d_mode()
            if current and current != self._active_ccd:
                self._saved_ccd = current
                ok, message = cpu_tools.set_x3d_mode(self._active_ccd)
                if not ok:
                    self._log(f"[Game Mode] X3D reactivation failed: {message}")
        by_pid = {int(p["pid"]): p for p in records}
        memberships = {}
        ended = []
        for token, session in list(self.sessions.items()):
            members = set()
            root_pid = int(session["root_pid"])
            root_current = _pid_matches(root_pid, float(session["root_start_time"]))
            for p in records:
                pid = int(p["pid"])
                if (_process_marker(pid) == token or
                        (root_current and _descends_from(pid, root_pid, by_pid))):
                    members.add((pid, float(p.get("create_time", 0.0))))
            if not members:
                ended.append(token)
            else:
                for identity in members:
                    memberships[identity] = session
        for token in ended:
            session = self.sessions.pop(token)
            self._log(f"[Game Mode] Ended {session['game_name']} ({token[:8]})")
        if ended:
            if self.sessions:
                self._persist()
            else:
                self._restore_ccd()
        return memberships

    def session_for_pid(self, pid: int, create_time: float = 0.0):
        marker = _process_marker(pid)
        if marker in self.sessions:
            return self.sessions[marker]
        for session in self.sessions.values():
            if pid == int(session["root_pid"]):
                if not create_time or create_time == float(session["root_start_time"]):
                    return session
        return None

    @staticmethod
    def launch_has_started(session: dict, pid: int, process_name: str) -> bool:
        if pid != int(session["root_pid"]):
            return True
        argv = session.get("argv", [])
        if not argv:
            return False
        expected = os.path.basename(str(argv[0]).replace("\\", "/")).casefold()
        return process_name.casefold() in {expected, os.path.splitext(expected)[0]}

    def shutdown(self):
        if self.sessions:
            self.sessions.clear()
            self._restore_ccd()


def _pid_matches(pid, create_time):
    try:
        import psutil
        return psutil.Process(pid).create_time() == create_time
    except Exception:
        return False


def _process_marker(pid):
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    prefix = (MARKER_ENV + "=").encode()
    for item in raw.split(b"\0"):
        if item.startswith(prefix):
            return item[len(prefix):].decode(errors="replace")
    return None


def _descends_from(pid, root_pid, records):
    seen = set()
    while pid and pid not in seen:
        if pid == root_pid:
            return True
        seen.add(pid)
        record = records.get(pid)
        if record and "ppid" in record:
            pid = int(record["ppid"])
        else:
            try:
                text = Path(f"/proc/{pid}/stat").read_text()
                pid = int(text[text.rfind(")") + 1:].split()[1])
            except (OSError, ValueError, IndexError):
                return False
    return False


class GameIPCServer(threading.Thread):
    daemon = True

    def __init__(self, manager):
        super().__init__(name="process-lasso-game-ipc")
        self.manager = manager
        self._stop_event = threading.Event()
        self._socket = None

    def run(self):
        path = socket_path()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket = server
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(8)
        server.settimeout(.25)
        while not self._stop_event.is_set():
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                continue
            with connection:
                try:
                    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    _pid, uid, _gid = struct.unpack("3i", credentials)
                    if uid != os.getuid():
                        raise PermissionError("IPC peer is not the current user")
                    request = json.loads(connection.recv(1024 * 1024).decode())
                    response = self.manager.activate(request)
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                connection.sendall(json.dumps(response).encode())
        server.close()
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def stop(self):
        self._stop_event.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
