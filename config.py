"""Load/save config from ~/.config/process-lasso/config.json."""
from __future__ import annotations

import json
import os
import copy
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "process-lasso"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "version": 2,
    "rules": [],
    "cpu": {
        # Applied to every process not matched by a specific rule.
        # e.g. "8-15,24-31" pushes all background processes to CCD1 while
        # rules for steam/games keep them on CCD0 (3D V-Cache die).
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
        "display_refresh_interval_ms": 2000,
        "rule_enforce_interval_ms": 500,
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
    if game_mode.get("defaults_initialized", False):
        return config
    try:
        import cpu_park
        preferred = set(cpu_park.detect_topology().preferred)
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


def load() -> dict:
    """Load config, filling missing keys with defaults."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            merged = _deep_merge(DEFAULT_CONFIG, data)
            # Version 2 adds the Game Mode catalog and hardware-aware defaults;
            # existing rules and unrelated settings remain lossless.
            merged["version"] = 2
            needs_game_defaults = not merged.get("game_mode", {}).get(
                "defaults_initialized", False
            )
            merged = _initialize_game_mode_defaults(merged)
            if needs_game_defaults:
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
