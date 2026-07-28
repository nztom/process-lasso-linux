# Runtime process-state ownership

`MonitorThread._sync_processes()` detects both process exit and PID reuse.
Both events mean that the old process identity has ended, so both are routed
once through `ProcessRuntimeCleanup.forget_pid()`. The coordinator notifies
each owner; it does not take ownership of subsystem internals.

| Collection | Owner | Key | Lifetime | Cleanup trigger |
| --- | --- | --- | --- | --- |
| `_known_pids` | Monitor | PID | One scan's set of observed processes | Replaced after each process scan; removed identities are coordinated before replacement |
| `_known_tids_by_pid` | Monitor | PID to TID set | Current process identity and its last observed threads | Process exit or PID reuse; individual exited TIDs disappear on the next thread sync |
| `_manually_overridden_pids` | Monitor | PID | Current process identity | Process exit or PID reuse |
| `_original_affinities` | Monitor | PID | Current process identity, until restoration clears all entries | Process exit, PID reuse, or explicit restoration |
| `_process_cache` | Monitor | PID | Current process identity | Process exit or PID reuse; metrics mutate only in the worker thread |
| `_attempts_by_rule` | RuleEngine | Rule ID to PID counter | Current rule and process identity | Process exit/PID reuse, rule edit/removal, or rule reload |
| `_suppressed_rule_pids` | RuleEngine | `(rule_id, PID)` | Current rule and process identity | Process exit/PID reuse, rule edit/removal, or rule reload |
| `_affinity_seen` | RuleEngine | encoded boot/process/thread/rule identity | Current thread and rule identity | Process exit/PID reuse, rule edit/removal, or rule reload |
| `_affinity_drift_attempts` | RuleEngine | encoded boot/process/thread/rule identity | Current thread and rule identity | Process exit/PID reuse, rule edit/removal, rule reload, or successful convergence |
| `_affinity_released` | RuleEngine | encoded boot/process/thread/rule identity | Current thread and rule identity | Process exit/PID reuse, rule edit/removal, or rule reload |
| `ThreadPriorityState` ledgers | RuleEngine-owned component | persisted process/thread start-time identities | Until restoration or pruning proves the identity is gone | Pruned/flushed during process cleanup and normal enforcement; persistence supplies crash safety |
| `_states` | ProBalance | `ProcessIdentity(pid, create_time)` | Current process identity while sampled | Identity absence from a ProBalance snapshot, with coordinator cleanup retained as an eager path |

The remaining PID-only keys are protected by Monitor's synchronous reuse
detection and centralized cleanup before a replacement is applied. ProBalance
also consumes snapshots independently, so it uses `ProcessIdentity` to prevent
state transfer even if a caller omits the eager cleanup notification.
