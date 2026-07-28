"""Rule dataclass and RuleEngine for matching and applying per-process rules."""
from __future__ import annotations

import os
import re
import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional

import utils
from policy_models import (
    AbsoluteNicePolicy,
    EffectiveProcessPolicy,
    IoPriorityPolicy,
    OffsetNicePolicy,
)
from thread_priority_state import ThreadPriorityState, thread_identity

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
    nice_mode: str = "absolute"
    nice_offset: int = 0
    nice_floor: int = -15
    nice_ceiling: int = 19
    ionice_class: Optional[int] = None
    ionice_level: Optional[int] = None
    enabled: bool = True
    force_apply: bool = False

    def __post_init__(self):
        if self.nice_mode not in ("absolute", "offset"):
            raise ValueError("nice_mode must be 'absolute' or 'offset'")
        if not -20 <= self.nice_floor <= self.nice_ceiling <= 19:
            raise ValueError("nice bounds must satisfy -20 <= floor <= ceiling <= 19")
        if self.nice is not None and not -20 <= self.nice <= 19:
            raise ValueError("nice must be between -20 and 19")
        if self.ionice_class is not None and (
            type(self.ionice_class) is not int
            or not 0 <= self.ionice_class <= 3
        ):
            raise ValueError("ionice_class must be an integer from 0 to 3")
        if self.ionice_level is not None and (
            type(self.ionice_level) is not int
            or not 0 <= self.ionice_level <= 7
        ):
            raise ValueError("ionice_level must be None or an integer from 0 to 7")

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        mode = d.get("nice_mode", "absolute")
        if mode not in ("absolute", "offset"):
            raise ValueError("nice_mode must be 'absolute' or 'offset'")
        floor = int(d.get("nice_floor", -15))
        ceiling = int(d.get("nice_ceiling", 19))
        if not -20 <= floor <= ceiling <= 19:
            raise ValueError("nice bounds must satisfy -20 <= floor <= ceiling <= 19")
        nice = d.get("nice")
        if nice is not None and not -20 <= int(nice) <= 19:
            raise ValueError("nice must be between -20 and 19")
        ionice_class = d.get("ionice_class")
        ionice_level = d.get("ionice_level")
        if ionice_class is not None:
            ionice_class = int(ionice_class)
        if ionice_level is not None:
            ionice_level = int(ionice_level)
        return cls(
            rule_id=d.get("rule_id", str(uuid.uuid4())),
            name=d.get("name", ""),
            pattern=d.get("pattern", ""),
            match_type=d.get("match_type", "contains"),
            affinity=d.get("affinity"),
            nice=None if nice is None else int(nice),
            nice_mode=mode,
            nice_offset=int(d.get("nice_offset", 0)),
            nice_floor=floor,
            nice_ceiling=ceiling,
            ionice_class=ionice_class,
            ionice_level=ionice_level,
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
            "nice_mode": self.nice_mode,
            "nice_offset": self.nice_offset,
            "nice_floor": self.nice_floor,
            "nice_ceiling": self.nice_ceiling,
            "ionice_class": self.ionice_class,
            "ionice_level": self.ionice_level,
            "enabled": self.enabled,
            "force_apply": self.force_apply,
        }

    def matches(self, proc_name: str) -> bool:
        """Return True if proc_name matches this rule."""
        if not self.enabled or not self.pattern:
            return False
        return self.pattern_matches(proc_name)

    def pattern_matches(self, proc_name: str) -> bool:
        """Match a name regardless of enabled state for rule-management UI."""
        if not self.pattern:
            return False
        if self.match_type == "exact":
            # Process names are identifiers rather than user-facing text.  In
            # particular, Wine may preserve the executable's mixed-case name
            # while a rule was created from a lower-case comm/display value.
            return proc_name.casefold() == self.pattern.casefold()
        elif self.match_type == "regex":
            try:
                return bool(re.search(self.pattern, proc_name))
            except re.error:
                return False
        else:  # contains
            return self.pattern.lower() in proc_name.lower()

class RuleEngine:
    """Holds the list of rules and applies them to processes."""

    def __init__(self, priority_state: ThreadPriorityState | None = None):
        self._rules: list[Rule] = []
        self._attempts_by_rule: dict[str, dict[int, int]] = {}
        self._suppressed_rule_pids: set[tuple[str, int]] = set()
        self._affinity_seen: set[str] = set()
        self._affinity_drift_attempts: dict[str, int] = {}
        self._affinity_released: set[str] = set()
        self._log_callback = None  # callable(str) for UI log
        self._priority_state = priority_state or ThreadPriorityState()

    def set_log_callback(self, cb):
        self._log_callback = cb

    def flush_priority_state(self):
        self._priority_state.flush()

    def _log(self, msg: str):
        log.info(msg)
        if self._log_callback:
            self._log_callback(msg)

    def load_rules(self, rules_list: list[dict]):
        loaded = []
        for raw in rules_list:
            try:
                loaded.append(Rule.from_dict(raw))
            except (TypeError, ValueError) as exc:
                log.warning("Ignoring invalid imported rule: %s", exc)
        self._rules = loaded
        self._attempts_by_rule.clear()
        self._suppressed_rule_pids.clear()
        self._affinity_seen.clear()
        self._affinity_drift_attempts.clear()
        self._affinity_released.clear()

    def get_rules(self) -> list[Rule]:
        return list(self._rules)

    def add_rule(self, rule: Rule):
        self._rules.append(rule)

    def remove_rule(self, rule_id: str):
        self._rules = [r for r in self._rules if r.rule_id != rule_id]
        self._attempts_by_rule.pop(rule_id, None)
        self._suppressed_rule_pids = {
            key for key in self._suppressed_rule_pids if key[0] != rule_id
        }
        self._clear_affinity_runtime(rule_id)

    def update_rule(self, rule: Rule):
        self._attempts_by_rule.pop(rule.rule_id, None)
        self._suppressed_rule_pids = {
            key for key in self._suppressed_rule_pids if key[0] != rule.rule_id
        }
        self._clear_affinity_runtime(rule.rule_id)
        for i, r in enumerate(self._rules):
            if r.rule_id == rule.rule_id:
                self._rules[i] = rule
                return

    def to_dict_list(self) -> list[dict]:
        return [r.to_dict() for r in self._rules]

    def matches_process(self, proc_name: str) -> bool:
        """Return True when at least one enabled rule matches a process name."""
        return any(rule.matches(proc_name) for rule in self._rules)

    def effective_policy(self, proc_name: str) -> EffectiveProcessPolicy:
        """Return the typed final policy produced by matching enabled rules.

        Rules are applied in list order, so a later matching rule with the same
        setting wins. This is the authoritative effective-policy merge.
        """
        affinity = None
        nice = None
        ionice = None
        for rule in self._rules:
            if not rule.matches(proc_name):
                continue
            if rule.affinity is not None:
                affinity = rule.affinity
            if rule.nice is not None:
                if rule.nice_mode == "offset":
                    nice = OffsetNicePolicy(
                        offset=rule.nice_offset,
                        floor=rule.nice_floor,
                        ceiling=rule.nice_ceiling,
                    )
                else:
                    nice = AbsoluteNicePolicy(rule.nice)
            if rule.ionice_class is not None:
                ionice = IoPriorityPolicy(rule.ionice_class, rule.ionice_level)
        return EffectiveProcessPolicy(
            affinity=affinity,
            nice=nice,
            ionice=ionice,
        )

    def forget_pid(self, pid: int):
        """Discard runtime attempt state after a process exits."""
        for attempts in self._attempts_by_rule.values():
            attempts.pop(pid, None)
        self._suppressed_rule_pids = {
            key for key in self._suppressed_rule_pids if key[1] != pid
        }
        pid_marker = f":{pid}:"
        self._affinity_seen = {
            key for key in self._affinity_seen if pid_marker not in key
        }
        self._affinity_drift_attempts = {
            key: attempts for key, attempts in self._affinity_drift_attempts.items()
            if pid_marker not in key
        }
        self._affinity_released = {
            key for key in self._affinity_released if pid_marker not in key
        }
        self._priority_state.prune()
        self._priority_state.flush_if_due()

    def suppress_pid(self, pid: int):
        """Stop all current rules from overriding a manual process change."""
        for rule in self._rules:
            self._suppressed_rule_pids.add((rule.rule_id, pid))
            self._attempts_by_rule.setdefault(rule.rule_id, {})[pid] = RULE_APPLY_ATTEMPTS

    def _can_apply(self, rule: Rule, pid: int) -> bool:
        attempts = self._attempts_by_rule.get(rule.rule_id, {})
        return rule.force_apply or (
            (rule.rule_id, pid) not in self._suppressed_rule_pids
            and attempts.get(pid, 0) < RULE_APPLY_ATTEMPTS
        )

    def _record_attempt(self, rule: Rule, pid: int):
        attempts = self._attempts_by_rule.setdefault(rule.rule_id, {})
        attempts[pid] = attempts.get(pid, 0) + 1

    def _clear_affinity_runtime(self, rule_id: str):
        suffix = f":{rule_id}"
        self._affinity_seen = {
            key for key in self._affinity_seen if not key.endswith(suffix)
        }
        self._affinity_drift_attempts = {
            key: attempts for key, attempts in self._affinity_drift_attempts.items()
            if not key.endswith(suffix)
        }
        self._affinity_released = {
            key for key in self._affinity_released if not key.endswith(suffix)
        }

    def _effective_affinity_rule(self, proc_name: str) -> Rule | None:
        result = None
        for rule in self._rules:
            if rule.matches(proc_name) and rule.affinity is not None:
                result = rule
        return result

    def _apply_affinity_policy(
        self, pid: int, proc_name: str, tids: list[int] | None = None
    ) -> list[str]:
        """Place new threads once, then selectively correct affinity drift."""
        rule = self._effective_affinity_rule(proc_name)
        if rule is None or (
            not rule.force_apply
            and (rule.rule_id, pid) in self._suppressed_rule_pids
        ):
            return []
        desired = utils.cpulist_to_online_set(rule.affinity)
        if not desired:
            # A rule containing only offline CPUs is temporarily inapplicable,
            # not drifting. It will be retried after those CPUs return.
            return []
        effective_affinity = utils._cpuset_to_cpulist(desired)
        actions = []
        for tid in tids if tids is not None else utils.get_process_tids(pid):
            try:
                identity = thread_identity(
                    pid, tid, rule.rule_id, self._priority_state.boot_id
                )
                current = set(os.sched_getaffinity(tid))
            except (OSError, ValueError, ProcessLookupError):
                continue
            first_seen = identity not in self._affinity_seen
            self._affinity_seen.add(identity)
            if current == desired:
                continue
            attempts = self._affinity_drift_attempts.get(identity, 0)
            if not first_seen and not rule.force_apply and attempts >= RULE_APPLY_ATTEMPTS:
                if identity not in self._affinity_released:
                    self._affinity_released.add(identity)
                    self._log(
                        f"[Rule:{rule.name}] Released affinity drift on "
                        f"{proc_name}({tid}) after {RULE_APPLY_ATTEMPTS} corrections"
                    )
                continue
            if not first_seen:
                self._affinity_drift_attempts[identity] = attempts + 1
            if not utils.set_thread_affinity(tid, effective_affinity):
                continue
            kind = "initial affinity" if first_seen else "affinity drift"
            attempt = "" if first_seen or rule.force_apply else (
                f" (correction {attempts + 1}/{RULE_APPLY_ATTEMPTS})"
            )
            msg = (
                f"[Rule:{rule.name}] Corrected {kind}={rule.affinity} on "
                f"{proc_name}({tid}){attempt}"
            )
            self._log(msg)
            actions.append(msg)
        return actions

    def _effective_nice_rule(self, proc_name: str) -> Rule | None:
        result = None
        for rule in self._rules:
            if rule.matches(proc_name) and rule.nice is not None:
                result = rule
        return result

    def _prepare_absolute_threads(
        self, rule: Rule, pid: int, tids: list[int], original_nice_hint: int | None = None
    ) -> dict[int, str]:
        """Persist pre-Absolute baselines before the existing clamp is applied."""
        pending: dict[str, dict] = {}
        keyed: dict[int, str] = {}
        for tid in tids:
            try:
                key = thread_identity(pid, tid, rule.rule_id, self._priority_state.boot_id)
                keyed[tid] = key
                entry = self._priority_state.get(key)
                corrected = False
                if original_nice_hint is not None:
                    corrected = self._priority_state.replace_original_for_identity(
                        key, original_nice_hint
                    )
                    entry = self._priority_state.get(key)
                if entry is not None:
                    if corrected:
                        pending[key] = {
                            **entry,
                            "original_nice": original_nice_hint,
                            "mode": "absolute",
                            "target_nice": rule.nice,
                        }
                    continue
                inferred = None
                original = self._priority_state.original_for_identity(key)
                if original is None:
                    if original_nice_hint is not None:
                        original = original_nice_hint
                    else:
                        observed = utils.get_thread_nice(tid)
                        inferred = self._priority_state.inferred_original_for_process_target(
                            key, observed
                        )
                        original = inferred if inferred is not None else observed
                pending[key] = {
                    "original_nice": original,
                    "original_source": (
                        "startup" if original_nice_hint is not None
                        else "inherited_target" if inferred is not None else "observed"
                    ),
                    "mode": "absolute",
                    "target_nice": rule.nice,
                }
            except (OSError, ValueError, ProcessLookupError):
                continue
        self._priority_state.set_pending_many(pending)
        return keyed

    def _finish_absolute_threads(self, keyed: dict[int, str], target: int, applied: bool):
        for key in keyed.values():
            if applied:
                self._priority_state.set_applied(key, target)
            else:
                self._priority_state.set_failed(key)

    def _apply_offset_threads(
        self, rule: Rule, pid: int, tids: list[int], proc_name: str,
        original_nice_hint: int | None = None,
    ) -> list[str]:
        groups: dict[int, list[tuple[int, str]]] = {}
        pending: dict[str, dict] = {}
        for tid in tids:
            try:
                key = thread_identity(pid, tid, rule.rule_id, self._priority_state.boot_id)
                entry = self._priority_state.get(key)
                if original_nice_hint is not None:
                    self._priority_state.replace_original_for_identity(
                        key, original_nice_hint
                    )
                    entry = self._priority_state.get(key)
                inferred = None
                original = (
                    int(entry["original_nice"])
                    if entry is not None and "original_nice" in entry
                    else self._priority_state.original_for_identity(key)
                )
                if original is None:
                    if original_nice_hint is not None:
                        original = original_nice_hint
                    else:
                        observed = utils.get_thread_nice(tid)
                        inferred = self._priority_state.inferred_original_for_process_target(
                            key, observed
                        )
                        original = inferred if inferred is not None else observed
                target = max(
                    rule.nice_floor,
                    min(rule.nice_ceiling, original + rule.nice_offset),
                )
                same = (
                    entry is not None
                    and entry.get("offset") == rule.nice_offset
                    and entry.get("floor") == rule.nice_floor
                    and entry.get("ceiling") == rule.nice_ceiling
                    and entry.get("target_nice") == target
                )
                drift_attempts = int(entry.get("drift_attempts", 0)) if entry else 0
                source = (
                    "startup" if original_nice_hint is not None
                    else "inherited_target" if inferred is not None else "observed"
                )
                if same and entry.get("status") == "applied":
                    observed = utils.get_thread_nice(tid)
                    if observed == target:
                        continue
                    if not rule.force_apply and drift_attempts >= RULE_APPLY_ATTEMPTS:
                        if not entry.get("released_logged"):
                            released = {**entry, "released_logged": True}
                            self._priority_state.set_pending_many({key: released})
                            self._priority_state.set_applied(key, target)
                            self._log(
                                f"[Rule:{rule.name}] Released nice drift on "
                                f"{proc_name}({tid}) after "
                                f"{RULE_APPLY_ATTEMPTS} corrections"
                            )
                        continue
                    drift_attempts += 1
                    if observed != original:
                        # A third value is a new application/external baseline.
                        # Persist it before applying our offset so it cannot
                        # compound after a crash or restart.
                        self._priority_state.replace_original_for_identity(
                            key, observed
                        )
                        original = observed
                        source = "rebased"
                        target = max(
                            rule.nice_floor,
                            min(rule.nice_ceiling, original + rule.nice_offset),
                        )
                    else:
                        source = "restored_baseline"
                pending[key] = {
                    "original_nice": original, "offset": rule.nice_offset,
                    "original_source": source,
                    "floor": rule.nice_floor, "ceiling": rule.nice_ceiling,
                    "target_nice": target, "drift_attempts": drift_attempts,
                }
                groups.setdefault(target, []).append((tid, key))
            except (OSError, ValueError, ProcessLookupError):
                continue
        self._priority_state.set_pending_many(pending)
        actions = []
        for target, keyed in groups.items():
            succeeded = utils.set_nice_threads([tid for tid, _ in keyed], target)
            for tid, key in keyed:
                if tid in succeeded:
                    self._priority_state.set_applied(key, target)
                else:
                    self._priority_state.set_failed(key)
            if succeeded:
                msg = f"[Rule:{rule.name}] Offset nice={rule.nice_offset:+d} [{rule.nice_floor}, {rule.nice_ceiling}] on {proc_name}({pid}), {len(succeeded)} thread(s)"
                self._log(msg)
                actions.append(msg)
        return actions

    def apply_to_process(
        self, pid: int, proc_name: str, original_nice_hint: int | None = None
    ) -> list[str]:
        """Apply all matching rules to a process. Returns list of action strings."""
        actions = self._apply_affinity_policy(pid, proc_name)
        nice_rule = self._effective_nice_rule(proc_name)
        for rule in self._rules:
            if not rule.matches(proc_name) or not self._can_apply(rule, pid):
                continue
            if not rule.force_apply:
                self._record_attempt(rule, pid)
            if rule is nice_rule and rule.nice is not None and rule.nice_mode == "absolute":
                keyed = self._prepare_absolute_threads(
                    rule, pid, utils.get_process_tids(pid), original_nice_hint
                )
                applied = utils.set_nice(pid, rule.nice)
                self._finish_absolute_threads(keyed, rule.nice, applied)
                if applied:
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
        if (
            nice_rule
            and nice_rule.nice_mode == "offset"
            and (
                nice_rule.force_apply
                or (nice_rule.rule_id, pid) not in self._suppressed_rule_pids
            )
        ):
            actions.extend(self._apply_offset_threads(
                nice_rule, pid, utils.get_process_tids(pid), proc_name,
                original_nice_hint,
            ))
        self._priority_state.flush_if_due()
        return actions

    def apply_to_thread(self, pid: int, tid: int, proc_name: str) -> list[str]:
        """Apply non-forced matching rules once to a newly observed thread."""
        actions = self._apply_affinity_policy(pid, proc_name, [tid])
        nice_rule = self._effective_nice_rule(proc_name)
        for rule in self._rules:
            # Forced rules already reapply to every process thread on each
            # enforcement pass, so doing so here would duplicate the work.
            if (
                rule.force_apply
                or (rule.rule_id, pid) in self._suppressed_rule_pids
                or not rule.matches(proc_name)
            ):
                continue
            if rule is nice_rule and rule.nice is not None and rule.nice_mode == "absolute":
                keyed = self._prepare_absolute_threads(rule, pid, [tid])
                applied = utils.set_thread_nice(tid, rule.nice)
                self._finish_absolute_threads(keyed, rule.nice, applied)
                if applied:
                    msg = (
                        f"[Rule:{rule.name}] Set nice={rule.nice} on "
                        f"new thread {proc_name}({tid})"
                    )
                    self._log(msg)
                    actions.append(msg)
            if rule.ionice_class is not None:
                if utils.set_ionice(tid, rule.ionice_class, rule.ionice_level):
                    msg = (
                        f"[Rule:{rule.name}] Set ionice class="
                        f"{rule.ionice_class} level={rule.ionice_level} on "
                        f"new thread {proc_name}({tid})"
                    )
                    self._log(msg)
                    actions.append(msg)
        if (
            nice_rule
            and nice_rule.nice_mode == "offset"
            and (
                nice_rule.force_apply
                or (nice_rule.rule_id, pid) not in self._suppressed_rule_pids
            )
        ):
            actions.extend(self._apply_offset_threads(nice_rule, pid, [tid], proc_name))
        self._priority_state.flush_if_due()
        return actions
