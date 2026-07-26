# Process and Rule Model Cleanup

## Purpose

The application has a coherent persisted `Rule` model and a shared observed
process-record shape, but it does not yet have one explicit read model joining
observed process state with effective policy and runtime enforcement state.
Today, GUI consumers independently combine a `ProcessInfo` snapshot with
`RuleEngine.effective_settings()`. This has already caused one visible bug: the
Current CPU Priority dialog initially showed the process leader's derived nice
value as an absolute value instead of showing the active offset rule.

This cleanup must be incremental. Do not rewrite monitoring or enforcement and
do not replace the worker-to-GUI snapshot copy with shared mutable objects.
The queued-signal boundary and detached snapshots are intentional thread-safety
features.

## Current architecture

- `process_info.py`
  - `ProcessInfo` is a `TypedDict` containing observed identity and metrics.
  - It has no effective-rule, manual-override, or enforcement fields.
- `monitor.py`
  - `Monitor._process_cache: dict[int, ProcessInfo]` is the worker-owned live
    cache.
  - Detached dictionary copies are emitted to the GUI.
  - Known TIDs, manual overrides, original affinities, and gaming nice state
    are separate PID-indexed collections.
- `rules.py`
  - `Rule` is the canonical persisted policy model.
  - `RuleEngine` owns rule ordering, matching, enforcement attempts,
    suppression, affinity drift state, and offset-nice application.
  - `effective_settings(name)` returns a loosely typed merged dictionary;
    later matching rules win independently for each setting.
- `thread_priority_state.py`
  - Persists per-thread identities and original nice baselines needed for
    crash-safe offset rules.
- `probalance.py`
  - Maintains independent per-PID throttling state.
- `gui/process_table.py`
  - Stores a detached `list[ProcessInfo]`.
  - Repeatedly calls `RuleEngine.effective_settings(proc["name"])` while
    sorting/rendering and when opening some context-menu dialogs.
  - Expanded thread rows use a separate untyped dictionary shape.
- `gui/rules_panel.py` and `gui/dialogs.py`
  - Operate directly on `Rule` objects, which is desirable.
- `config.py`
  - Persists rules as dictionaries through `Rule.to_dict()`/`from_dict()`.

## Invariants to preserve

Every task below must preserve these behaviors unless its task explicitly says
otherwise:

1. `RuleEngine` remains the authoritative owner of rules and enforcement.
2. Rules are applied in list order; the last matching rule that specifies a
   particular setting wins for that setting.
3. Disabled rules do not contribute to effective policy or enforcement.
4. A successful Current affinity, priority, or I/O action suppresses ordinary
   rules for that running PID until it exits. `force_apply=True` still wins.
5. New threads inherit applicable rules unless their PID is suppressed.
6. Offset nice rules use the persisted original-thread baseline and must never
   compound on restart, drift correction, or unchanged dialog acceptance.
7. PID reuse is distinguished by process/thread start time where persistent
   state requires it.
8. Worker-owned records are copied before crossing into the GUI thread.
9. User configuration under `~/.config/process-lasso` is never overwritten by
   tests or deployment.
10. Existing unrelated working-tree changes must be preserved.

## Standard verification

Run these after every task:

```bash
python3 -m compileall -q .
python3 -m unittest discover -q -s tests -p 'test_*.py'
git diff --check
```

At the time this TODO was written, the suite contained 106 passing tests. The
count may increase; no existing test should regress.

## Manageable execution chunks

Use these as the actual units of work. A fresh agent should take exactly one
unchecked chunk, read the referenced detailed task below, implement it, run the
standard verification, and stop. Do not combine chunks merely because they are
in the same phase.

- [x] **Chunk 1 — Rule merge characterization tests.** Add tests for per-field
  last-wins precedence and disabled rules. Files: `rules.py`,
  `tests/test_thread_priority_state.py` or a focused new rule-model test file.
  Detailed reference: Phase 1. No production behavior changes.
- [x] **Chunk 2 — Suppression characterization tests.** Cover manual suppression
  for absolute nice, offset nice, affinity, I/O, new threads, and forced rules.
  Files: `rules.py`, `monitor.py`, relevant tests. Detailed reference: Phase 1.
- [x] **Chunk 3 — Identity and snapshot characterization tests.** Cover process
  exit, PID reuse, transient-state cleanup, and detached worker snapshots.
  Files: `monitor.py`, `rules.py`, `probalance.py`, relevant tests. Detailed
  reference: Phase 1.
- [x] **Chunk 4 — Typed nice-policy values.** Add immutable absolute and offset
  policy types with validation and formatting tests. Do not migrate consumers.
  Prefer a small new model module. Detailed reference: Phase 2.
- [x] **Chunk 5 — Typed effective policy merge.** Add
  `EffectiveProcessPolicy`, implement the authoritative merge in `RuleEngine`,
  and retain the old dictionary API as a compatibility adapter. Files:
  `rules.py`, the new model module, tests. Detailed reference: Phase 2.
- [x] **Chunk 6 — Immutable observed snapshot.** Introduce an immutable GUI-safe
  observed process snapshot while retaining the worker's mutable cache. Prove
  the queued boundary remains detached. Files: `process_info.py`, `monitor.py`,
  tests. Detailed reference: Phase 3.
- [x] **Chunk 7 — Joined process-policy view assembly.** Add
  `ProcessPolicyView` and construct it once per GUI refresh. Include read-only
  manual-suppression status. Do not migrate table rendering yet. Files:
  `process_info.py` or the model module, `monitor.py`/`main_window.py`, tests.
  Detailed reference: Phase 3.
- [x] **Chunk 8 — Process-table rendering migration.** Move sorting and Current/
  Always column rendering to the joined view. Remove repeated effective-policy
  lookups from rendering only. Files: `gui/process_table.py` and tests. Detailed
  reference: Phase 4.
- [x] **Chunk 9 — Context-menu migration.** Move affinity, priority, I/O, and
  Clear Rules context actions to typed view inputs. Preserve manual suppression
  and unchanged-offset behavior. Files: `gui/process_table.py`,
  `gui/dialogs.py`, tests. Detailed reference: Phase 4.
- [x] **Chunk 10 — Typed thread snapshots.** Replace expanded-row dictionaries
  with `ThreadSnapshot` while preserving lazy sampling and TID start-time
  identity. Files: `process_info.py`, `gui/process_table.py`, tests. Detailed
  reference: Phase 5.
- [x] **Chunk 11 — Runtime-state ownership audit and cleanup contract.** Document
  every PID/TID-indexed collection and add one centralized exit/reuse cleanup
  coordinator. Do not relocate subsystem internals in this chunk. Files:
  `monitor.py`, `rules.py`, `probalance.py`, tests. Detailed reference: Phase 6.
- [x] **Chunk 12 — Identity-key hardening.** Introduce `ProcessIdentity` only
  where the Chunk 11 audit shows PID reuse can corrupt state. Migrate one state
  category at a time with tests. Detailed reference: Phase 6.
- [x] **Chunk 13 — Compatibility and formatting cleanup.** Remove the old
  effective-policy dictionary adapter and consolidate pure formatters after all
  GUI consumers are typed. Files: model/rule modules and GUI tests. Detailed
  reference: Phase 7.
- [ ] **Chunk 14 — Integration and deployment audit.** Run automated and manual
  checks, then deploy through the user service workflow. Detailed reference:
  Phase 8. This chunk must not contain architectural refactoring.

The sections below provide the context and acceptance criteria for those small
chunks; they are phases, not single implementation assignments.

## Phase 1 reference: Lock down cross-model behavior with characterization tests

**Goal:** Establish tests around the boundaries that a later refactor will
change, without changing production behavior.

**Read first:** `process_info.py`, `monitor.py`, `rules.py`,
`thread_priority_state.py`, `probalance.py`, `gui/process_table.py`, and the
corresponding files under `tests/`.

Add focused tests for:

- Multiple matching rules where different rules supply affinity, nice, and I/O
  settings, including last-wins precedence per field.
- Disabled rules being absent from effective settings.
- Manual suppression affecting absolute nice, offset nice, affinity, I/O, and
  newly observed threads; forced rules must remain active.
- An unchanged active offset shown in the Current priority dialog producing the
  existing live target rather than applying the offset twice.
- Offset changes relative to an already applied offset (for example, live `-6`
  from policy `-5`; changing policy presentation to `-4` should target `-5`).
- Process exit and PID reuse clearing all transient suppression/attempt state.
- Worker snapshots being detached from `_process_cache`.

Prefer unit tests with mocked syscall helpers. Do not require root, mutate real
process priorities, or rely on timing sleeps.

**Acceptance criteria:** Tests document all invariants above and pass against
the current implementation. Production changes, if any, are limited to small
testability seams with no behavior change.

## Phase 2 reference: Introduce typed effective-policy models

**Depends on:** Task 1.

**Goal:** Replace the loosely typed dictionary returned by
`RuleEngine.effective_settings()` with an explicit, immutable representation
while retaining a compatibility path during migration.

Suggested model (names may be refined):

```python
@dataclass(frozen=True)
class EffectiveProcessPolicy:
    affinity: str | None = None
    nice: NicePolicy | None = None
    ionice: IoPolicy | None = None

@dataclass(frozen=True)
class AbsoluteNicePolicy:
    value: int

@dataclass(frozen=True)
class OffsetNicePolicy:
    offset: int
    floor: int
    ceiling: int
```

Use either a discriminated dataclass hierarchy or another representation that
makes invalid combinations impossible. Avoid retaining the current misleading
`Rule.nice` marker as the meaningful value for an offset policy.

Keep `Rule` as the persisted/editable policy model. The new model is the merged
read result, not a replacement for `Rule`.

**Acceptance criteria:**

- Effective policy has one authoritative merge implementation.
- Absolute and offset policies cannot be confused by consumers.
- Rule precedence and serialization remain unchanged.
- Existing consumers continue working through a temporary adapter or are
  migrated in the same small change.
- New tests compare complete typed policy objects rather than dictionary keys.

## Phase 3 reference: Introduce an immutable process-policy view for GUI consumption

**Depends on:** Tasks 1 and 2.

**Goal:** Give GUI consumers one typed read model containing observed process
state plus its effective policy. Do not move enforcement state into the GUI.

Suggested shape:

```python
@dataclass(frozen=True)
class ProcessPolicyView:
    observed: ProcessSnapshot
    effective_policy: EffectiveProcessPolicy
    manually_overridden: bool
```

Consider converting `ProcessInfo` from a mutable `TypedDict` into two layers:

- A worker-internal mutable metrics record, if mutation remains useful.
- An immutable snapshot/view emitted to the GUI.

Construct the joined view once per display snapshot, preferably before or at a
single GUI boundary. Do not call `effective_settings()` repeatedly per process
during sorting, rendering, and dialog creation.

Manual override state must be exposed read-only. Decide explicitly whether the
view reports only normal-rule suppression or also why it is suppressed. Keep
the first implementation minimal.

**Acceptance criteria:**

- The process table receives a collection of immutable joined views.
- Current and Always columns come from the same view instance.
- Context-menu dialogs use that same view rather than re-querying rules.
- Rule changes can refresh/rebuild policy portions immediately without waiting
  for the next metrics sample.
- No mutable worker record is shared with the GUI thread.

## Phase 4 reference: Migrate the process table and dialogs

**Depends on:** Task 3.

**Goal:** Remove ad hoc process/rule joins from `gui/process_table.py`.

Migrate:

- Sorting keys for Current and Always columns.
- Row rendering.
- CPU affinity Current/Always actions.
- CPU priority Current/Always actions, including offset presentation and
  unchanged-offset behavior.
- I/O priority Current/Always actions.
- Clear Rules matching and menu enablement, where appropriate.

Dialog constructors should accept typed values or small typed view models, not
whole mutable process dictionaries. Keep syscall execution outside passive
view models.

**Acceptance criteria:**

- `ProcessTable` no longer calls `RuleEngine.effective_settings()` during
  sorting, rendering, or Current dialog creation.
- No `dict.get("nice_mode")`-style policy introspection remains in the migrated
  GUI path.
- Existing UI text and manual-override behavior remain stable.
- Dialog tests cover absolute policy, offset policy, no policy, clamping,
  cancellation, success, and failure.

## Phase 5 reference: Type and unify thread snapshots

**Depends on:** Task 3. Can be performed independently of Task 4 after the view
model interfaces are settled.

**Goal:** Replace expanded-row thread dictionaries with an explicit
`ThreadSnapshot` model and attach them consistently to the process view or a
separate typed lazy result.

Preserve lazy thread sampling: collapsed processes should not incur detailed
per-thread CPU sampling. Preserve thread identity using TID plus start time;
TIDs alone are reusable.

**Acceptance criteria:**

- `ThreadSampler.read()` returns typed snapshots.
- Rendering and tests do not depend on undocumented dictionary keys.
- Expansion/collapse sampling behavior and CPU calculations remain unchanged.
- Thread rows remain excluded from process actions.

## Phase 6 reference: Consolidate runtime process state ownership

**Depends on:** Tasks 1 and 3. This is higher risk and should be split into
separate commits by state category.

**Goal:** Make transient state ownership explicit without creating one giant
mutable process object.

Audit these collections:

- Monitor: `_known_pids`, `_known_tids_by_pid`, `_manually_overridden_pids`,
  `_original_affinities`, `_gaming_niced`, `_process_cache`.
- RuleEngine: `_attempts_by_rule`, `_suppressed_rule_pids`, affinity drift sets,
  and `ThreadPriorityState`.
- ProBalance: `_states`.

For each collection, document its owner, identity key, lifetime, and cleanup
trigger. Introduce a small `ProcessIdentity(pid, create_time)` value where it
materially prevents PID-reuse errors. Do not move ProBalance or enforcement
internals into a GUI-oriented model.

Centralize exit/reuse cleanup orchestration so every subsystem is notified
exactly once. Subsystems may retain their own internal state.

**Acceptance criteria:**

- Every transient collection has one clear owner and lifecycle.
- PID reuse tests cover Monitor, RuleEngine, ProBalance, and offset ledgers.
- Manual override state is not duplicated unless one copy is an explicit
  read-only projection.
- There is no reduction in crash safety for offset priority restoration.

## Phase 7 reference: Remove compatibility adapters and duplicated formatting

**Depends on:** Tasks 2 through 6.

**Goal:** Finish the migration only after all consumers use typed models.

Remove:

- Dictionary compatibility adapters for effective policy.
- Repeated absolute/offset formatting branches across rules panel, process
  table, and dialogs; use one pure formatter per policy type.
- Obsolete `ProcessInfo` dictionary access in GUI code.
- Redundant manual-override or effective-policy lookups discovered during the
  migration.

Do not remove `Rule.to_dict()`/`from_dict()`; those remain the persistence
boundary.

**Acceptance criteria:**

- `rg 'effective_settings|nice_mode|nice_offset' gui` shows only intentional
  editor/persistence use, not ad hoc read-model joins.
- Formatting tests cover every policy variant.
- Full verification passes and dead code is removed.

## Phase 8 reference: Final integration and deployment audit

**Depends on:** All previous tasks.

**Goal:** Verify behavior in the installed Ubuntu Desktop application.

Before deployment, run the standard verification commands. Then follow the
`deploy-process-lasso` skill/workflow: stop the user service, copy runtime root
and `gui/` Python modules to `~/.local/share/process-lasso`, restart the service,
compare key installed files, and inspect recent journal output.

Manual smoke checks:

1. An absolute Always priority displays and opens consistently.
2. An offset Always priority (for example `-5`) shows as offset in the Current
   dialog while displaying the live derived target separately.
3. Accepting the unchanged offset does not compound it.
4. Changing Current priority suppresses ordinary rules for that PID.
5. A force-applied rule overwrites the Current value as documented.
6. Affinity and I/O Current actions retain the same suppression behavior.
7. New threads receive policy before suppression and do not after suppression.
8. Process exit/relaunch clears the prior instance's manual override.
9. ProBalance throttle and restoration still work.

**Acceptance criteria:** Service is active with zero unexpected restarts, logs
contain no traceback/import errors, installed files match the source, and all
manual checks pass.

## Guidance for fresh agents

- Start by reading this entire file and the files listed in the selected task.
- Check `git status --short` before editing. The checkout may contain unrelated
  user changes; never discard or overwrite them.
- Work on one numbered task at a time. Do not opportunistically begin later
  migrations.
- Add tests before changing behavior-sensitive code.
- Use `apply_patch` for edits.
- Do not run `install.sh` for ordinary refreshes and do not alter the privileged
  helper unless explicitly requested.
- If an architectural choice would change rule semantics or persisted config,
  stop and ask the user rather than guessing.
