"""Canonical game identities and launcher-provider shims."""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


STEAM_APP_ID_KEYS = (
    "SteamAppId", "SteamGameId", "STEAM_COMPAT_APP_ID", "SteamOverlayGameId",
)


@dataclass(frozen=True)
class LaunchIdentity:
    game_id: str
    name: str
    source_aliases: tuple[str, ...]
    executable_aliases: tuple[str, ...]
    affinity: object = "inherit"
    nice: object = "inherit"


class IdentityProvider(Protocol):
    def resolve(self, environment: dict[str, str], argv: list[str]) -> tuple[str, str] | None: ...


def _steam_roots() -> list[Path]:
    home = Path.home()
    roots = [home / ".steam/steam", home / ".local/share/Steam"]
    library_files = [root / "steamapps/libraryfolders.vdf" for root in roots]
    for file in library_files:
        try:
            text = file.read_text(errors="replace")
        except OSError:
            continue
        for value in re.findall(r'"path"\s+"([^"]+)"', text):
            roots.append(Path(value.replace("\\\\", "\\")))
    return list(dict.fromkeys(roots))


def steam_manifests() -> dict[str, tuple[str, Path]]:
    """Scan current Steam libraries every launch and return appid metadata."""
    result = {}
    for root in _steam_roots():
        for manifest in (root / "steamapps").glob("appmanifest_*.acf"):
            try:
                text = manifest.read_text(errors="replace")
            except OSError:
                continue
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            installdir = re.search(r'"installdir"\s+"([^"]+)"', text)
            if appid and name:
                base = root / "steamapps/common"
                result[appid.group(1)] = (
                    name.group(1), base / (installdir.group(1) if installdir else "")
                )
    return result


class SteamProvider:
    def resolve(self, environment, argv):
        appid = next((environment.get(k) for k in STEAM_APP_ID_KEYS if environment.get(k)), None)
        if not appid or not str(appid).isdigit():
            return None
        manifest = steam_manifests().get(str(appid))
        return (f"steam:{appid}", manifest[0] if manifest else f"Steam {appid}")


def executable_alias(argv: list[str]) -> str:
    if not argv:
        return ""
    wrappers = {"gamemoderun", "env", "steam-runtime-launch-client", "proton", "proton-waitforexitandrun"}
    candidates = [str(arg) for arg in argv if arg and not str(arg).startswith("-")]
    raw = candidates[0]
    first = os.path.basename(raw.replace("\\", "/")).casefold()
    if first in wrappers:
        windows = [arg for arg in candidates[1:] if arg.casefold().endswith(".exe")]
        usable = [arg for arg in candidates[1:]
                  if os.path.basename(arg.replace("\\", "/")).casefold() not in wrappers]
        raw = windows[-1] if windows else (usable[0] if usable else raw)
    return os.path.basename(raw.replace("\\", "/")).casefold()


class GameCatalog:
    """Mutable adapter around the version-2 ``game_mode.games`` records."""

    def __init__(self, game_config: dict):
        self.config = game_config
        self.games = game_config.setdefault("games", [])

    def _view(self, record: dict) -> LaunchIdentity:
        return LaunchIdentity(
            str(record["id"]), str(record["name"]),
            tuple(record.get("source_aliases", [])),
            tuple(record.get("executable_aliases", [])),
            record.get("affinity", "inherit"), record.get("nice", "inherit"),
        )

    def resolve(self, argv: list[str], environment: dict[str, str], explicit: str | None = None):
        alias = executable_alias(argv)
        if explicit:
            matches = [g for g in self.games if explicit in (g.get("id"), g.get("name"))]
            if len(matches) == 1:
                return self._view(matches[0]), None
            return None, f"unknown explicit game profile: {explicit}"

        provider_result = SteamProvider().resolve(environment, argv)
        if provider_result:
            source, name = provider_result
            known = [g for g in self.games if source in g.get("source_aliases", [])]
            if known:
                record = known[0]
            else:
                by_name = [g for g in self.games if g.get("name", "").casefold() == name.casefold()]
                record = by_name[0] if len(by_name) == 1 else self._new(name)
                record.setdefault("source_aliases", []).append(source)
            self._learn_alias(record, alias)
            return self._view(record), None

        matches = [g for g in self.games if alias and alias in g.get("executable_aliases", [])]
        if len(matches) == 1:
            return self._view(matches[0]), None
        if len(matches) > 1:
            return None, f"ambiguous executable alias: {alias}"
        name = os.path.splitext(alias)[0] or "Game"
        record = self._new(name)
        self._learn_alias(record, alias)
        return self._view(record), None

    def _new(self, name):
        record = {"id": str(uuid.uuid4()), "name": name,
                  "source_aliases": [], "executable_aliases": [],
                  "affinity": "inherit", "nice": "inherit"}
        self.games.append(record)
        return record

    @staticmethod
    def _learn_alias(record, alias):
        # Basenames are learned conservatively: generic launcher/interpreter
        # names would create unsafe cross-game matches.
        unsafe = {"", "python", "python3", "wine", "wine64", "steam", "sh", "bash", "gamemoderun"}
        if alias not in unsafe and alias not in record.setdefault("executable_aliases", []):
            record["executable_aliases"].append(alias)


def effective_policy(game_config: dict, identity: LaunchIdentity | None) -> dict:
    result = {"affinity": game_config.get("affinity"), "nice": game_config.get("nice")}
    if identity:
        if identity.affinity != "inherit":
            result["affinity"] = None if identity.affinity == "disabled" else identity.affinity
        if identity.nice != "inherit":
            result["nice"] = None if identity.nice == "disabled" else identity.nice
    return result
