"""Rule dataclass and RuleEngine for matching and applying per-process rules."""
from __future__ import annotations

import re
import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional

import utils

log = logging.getLogger(__name__)

RULE_APPLY_ATTEMPTS = 10


@dataclass
class Rule:
    rule_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    pattern: str = ""
    match_type: str = "contains"   # "contains" | "exact" | "regex"
    affinity: Optional[str] = None
    nice: Optional[int] = None
    ionice_class: Optional[int] = None
    ionice_level: Optional[int] = None
    enabled: bool = True
    force_apply: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(
            rule_id=d.get("rule_id", str(uuid.uuid4())),
            name=d.get("name", ""),
            pattern=d.get("pattern", ""),
            match_type=d.get("match_type", "contains"),
            affinity=d.get("affinity"),
            nice=d.get("nice"),
            ionice_class=d.get("ionice_class"),
            ionice_level=d.get("ionice_level"),
            enabled=d.get("enabled", True),
            force_apply=d.get("force_apply", False),
        )

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "pattern": self.pattern,
            "match_type": self.match_type,
            "affinity": self.affinity,
            "nice": self.nice,
            "ionice_class": self.ionice_class,
            "ionice_level": self.ionice_level,
            "enabled": self.enabled,
            "force_apply": self.force_apply,
        }

    def matches(self, proc_name: str) -> bool:
        """Return True if proc_name matches this rule."""
        if not self.enabled or not self.pattern:
            return False
        if self.match_type == "exact":
            return proc_name == self.pattern
        elif self.match_type == "regex":
            try:
                return bool(re.search(self.pattern, proc_name))
            except re.error:
                return False
        else:  # contains
            return self.pattern.lower() in proc_name.lower()

class RuleEngine:
    """Holds the list of rules and applies them to processes."""

    def __init__(self):
        self._rules: list[Rule] = []
        self._attempts_by_rule: dict[str, dict[int, int]] = {}
        self._log_callback = None  # callable(str) for UI log

    def set_log_callback(self, cb):
        self._log_callback = cb

    def _log(self, msg: str):
        log.info(msg)
        if self._log_callback:
            self._log_callback(msg)

    def load_rules(self, rules_list: list[dict]):
        self._rules = [Rule.from_dict(r) for r in rules_list]
        self._attempts_by_rule.clear()

    def get_rules(self) -> list[Rule]:
        return list(self._rules)

    def add_rule(self, rule: Rule):
        self._rules.append(rule)

    def remove_rule(self, rule_id: str):
        self._rules = [r for r in self._rules if r.rule_id != rule_id]
        self._attempts_by_rule.pop(rule_id, None)

    def update_rule(self, rule: Rule):
        self._attempts_by_rule.pop(rule.rule_id, None)
        for i, r in enumerate(self._rules):
            if r.rule_id == rule.rule_id:
                self._rules[i] = rule
                return

    def to_dict_list(self) -> list[dict]:
        return [r.to_dict() for r in self._rules]

    def matches_process(self, proc_name: str) -> bool:
        """Return True when at least one enabled rule matches a process name."""
        return any(rule.matches(proc_name) for rule in self._rules)

    def effective_settings(self, proc_name: str) -> dict:
        """Return the final persistent settings produced by matching rules.

        Rules are applied in list order, so a later matching rule with the same
        setting wins.  This mirrors ``apply_to_process`` and is used by the
        process table's Always columns.
        """
        settings = {
            "affinity": None,
            "nice": None,
            "ionice_class": None,
            "ionice_level": None,
        }
        for rule in self._rules:
            if not rule.matches(proc_name):
                continue
            if rule.affinity is not None:
                settings["affinity"] = rule.affinity
            if rule.nice is not None:
                settings["nice"] = rule.nice
            if rule.ionice_class is not None:
                settings["ionice_class"] = rule.ionice_class
                settings["ionice_level"] = rule.ionice_level
        return settings

    def forget_pid(self, pid: int):
        """Discard runtime attempt state after a process exits."""
        for attempts in self._attempts_by_rule.values():
            attempts.pop(pid, None)

    def suppress_pid(self, pid: int):
        """Stop all current rules from overriding a manual process change."""
        for rule in self._rules:
            self._attempts_by_rule.setdefault(rule.rule_id, {})[pid] = RULE_APPLY_ATTEMPTS

    def _can_apply(self, rule: Rule, pid: int) -> bool:
        attempts = self._attempts_by_rule.get(rule.rule_id, {})
        return rule.force_apply or attempts.get(pid, 0) < RULE_APPLY_ATTEMPTS

    def _record_attempt(self, rule: Rule, pid: int):
        attempts = self._attempts_by_rule.setdefault(rule.rule_id, {})
        attempts[pid] = attempts.get(pid, 0) + 1

    def apply_to_process(self, pid: int, proc_name: str) -> list[str]:
        """Apply all matching rules to a process. Returns list of action strings."""
        actions = []
        for rule in self._rules:
            if not rule.matches(proc_name) or not self._can_apply(rule, pid):
                continue
            if not rule.force_apply:
                self._record_attempt(rule, pid)
            if rule.affinity is not None:
                if utils.set_affinity(pid, rule.affinity):
                    msg = f"[Rule:{rule.name}] Set affinity={rule.affinity} on {proc_name}({pid})"
                    self._log(msg)
                    actions.append(msg)
            if rule.nice is not None:
                if utils.set_nice(pid, rule.nice):
                    msg = f"[Rule:{rule.name}] Set nice={rule.nice} on {proc_name}({pid})"
                    self._log(msg)
                    actions.append(msg)
                else:
                    msg = f"[Rule:{rule.name}] nice={rule.nice} failed (root needed?) for {proc_name}({pid})"
                    self._log(msg)
                    actions.append(msg)
            if rule.ionice_class is not None:
                if utils.set_ionice(pid, rule.ionice_class, rule.ionice_level):
                    msg = f"[Rule:{rule.name}] Set ionice class={rule.ionice_class} level={rule.ionice_level} on {proc_name}({pid})"
                    self._log(msg)
                    actions.append(msg)
        return actions
