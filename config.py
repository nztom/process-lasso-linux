"""Load/save config from ~/.config/process-lasso/config.json."""
from __future__ import annotations

import json
import os
import copy
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "process-lasso"
CONFIG_FILE = CONFIG_DIR / "config.json"
MONITOR_INTERVAL_DEFAULT_MS = 1000
MONITOR_INTERVAL_MIN_MS = 500
MONITOR_INTERVAL_MAX_MS = 10000
LEGACY_MONITOR_INTERVAL_KEYS = (
    "process_scan_interval_ms",
    "display_refresh_interval_ms",
    "rule_enforce_interval_ms",
)

DEFAULT_GAME_ENVIRONMENT = [
    "__NV_PRIME_RENDER_OFFLOAD=1",
    "__GLX_VENDOR_LIBRARY_NAME=nvidia",
    "__VK_LAYER_NV_optimus=NVIDIA_only",
]

DEFAULT_CONFIG = {
    "version": 3,
    "process_policies": [],
    "cpu": {
        # Applied to non-game processes without an Always affinity policy;
        # Always nice and I/O-only policies still receive this default.
        # e.g. "8-15,24-31" pushes all background processes to CCD1 while
        # per-process policies can keep games on CCD0 (3D V-Cache die).
        # null = disabled.
        "default_affinity": None,
    },
    "probalance": {
        "enabled": True,
        "cpu_threshold_percent": 85.0,
        "consecutive_seconds": 3,
        "nice_adjustment": 10,
        "nice_floor": 15,
        "restore_threshold_percent": 40.0,
        "restore_hysteresis_seconds": 5,
        "exempt_patterns": ["kwin", "plasmashell", "systemd", "kthreadd", "Xorg", "xwayland"],
    },
    "monitor": {
        "interval_ms": MONITOR_INTERVAL_DEFAULT_MS,
    },
    "ui": {
        "start_minimized": False,
        "sort_column": "cpu_percent",
        "sort_order": "desc",
    },
    "game_mode": {
        "defaults_initialized": False,
        "ccd_preference": "cache",
        "affinity": None,
        "nice": None,
        "wrappers": [],
        "environment": DEFAULT_GAME_ENVIRONMENT,
        "games": [],
    },
}


def _compact_cpulist(cpus: set[int]) -> str | None:
    if not cpus:
        return None
    ordered = sorted(cpus)
    ranges = []
    start = end = ordered[0]
    for cpu in ordered[1:]:
        if cpu == end + 1:
            end = cpu
        else:
            ranges.append(f"{start}-{end}" if start != end else str(start))
            start = end = cpu
    ranges.append(f"{start}-{end}" if start != end else str(start))
    return ",".join(ranges)


def _initialize_game_mode_defaults(config: dict) -> dict:
    """Populate hardware-aware defaults once, preserving later user choices."""
    game_mode = config.setdefault("game_mode", {})
    game_mode.setdefault("wrappers", [])
    game_mode.setdefault("environment", copy.deepcopy(DEFAULT_GAME_ENVIRONMENT))
    if game_mode.get("defaults_initialized", False):
        return config
    try:
        import cpu_tools
        preferred = set(cpu_tools.get_cpu_info().topology.preferred)
    except Exception:
        preferred = set()
    game_mode["affinity"] = _compact_cpulist(preferred)
    game_mode["nice"] = {"type": "absolute", "value": -1}
    game_mode["defaults_initialized"] = True
    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively, returning new dict."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def monitor_interval_ms(config: dict) -> int:
    """Return the unified monitor cadence, accepting pre-migration configs."""
    monitor = config.get("monitor", {})
    if "interval_ms" in monitor:
        value = monitor["interval_ms"]
    else:
        value = next(
            (monitor[key] for key in LEGACY_MONITOR_INTERVAL_KEYS
             if key in monitor),
            MONITOR_INTERVAL_DEFAULT_MS,
        )
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = MONITOR_INTERVAL_DEFAULT_MS
    return max(MONITOR_INTERVAL_MIN_MS, min(MONITOR_INTERVAL_MAX_MS, value))


def _migrate_monitor_config(config: dict, source: dict | None = None) -> bool:
    """Replace legacy per-phase intervals with one global monitor interval."""
    monitor = config.setdefault("monitor", {})
    source = monitor if source is None else source
    normalized = monitor_interval_ms({"monitor": source})
    changed = (source.get("interval_ms") != normalized) or any(
        key in monitor for key in LEGACY_MONITOR_INTERVAL_KEYS
    )
    monitor["interval_ms"] = normalized
    for key in LEGACY_MONITOR_INTERVAL_KEYS:
        monitor.pop(key, None)
    return changed


def load() -> dict:
    """Load config, filling missing keys with defaults."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            merged = _deep_merge(DEFAULT_CONFIG, data)
            # Version 3 replaces user-authored rules with exact-name policies
            # managed exclusively through the Processes tab.
            merged["version"] = 3
            retired_rules = "rules" in data
            merged.pop("rules", None)
            merged.setdefault("process_policies", [])
            needs_game_defaults = not merged.get("game_mode", {}).get(
                "defaults_initialized", False
            )
            needs_game_environment = "environment" not in data.get("game_mode", {})
            needs_game_wrappers = "wrappers" not in data.get("game_mode", {})
            monitor_migrated = _migrate_monitor_config(
                merged, data.get("monitor", {})
            )
            merged = _initialize_game_mode_defaults(merged)
            if (needs_game_defaults or needs_game_environment
                    or needs_game_wrappers or monitor_migrated or retired_rules):
                save(merged)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    initialized = _initialize_game_mode_defaults(copy.deepcopy(DEFAULT_CONFIG))
    save(initialized)
    return initialized


def save(config: dict) -> None:
    """Atomically save config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
    tmp.replace(CONFIG_FILE)
