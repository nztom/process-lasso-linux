# Process policy semantics

Process Lasso uses different affinity and priority semantics depending on where
a policy is configured. The distinction is intentional: a one-time action can
set an exact state, while a persistent policy must coexist with applications
that manage their own threads.

| Policy source | When it applies | Affinity or nice semantics | Later application changes |
| --- | --- | --- | --- |
| Processes → Current affinity | Immediately | Writes one exact online CPU mask to every live thread and verifies the result, with one bounded retry for thread churn | Allowed; the matching Always affinity field is suppressed for that process identity after a successful manual write |
| Processes → Always affinity | At process discovery, for new threads, and during monitoring | Defines an allowed CPU boundary. A narrower in-bounds thread mask is preserved; an out-of-bounds mask is intersected with the boundary, or replaced by the full boundary if the intersection is empty | Corrected while enforcement remains active; non-forced rules stop correcting a persistently drifting thread after the bounded retry limit |
| Settings → Default affinity | At process discovery, when settings are reapplied, and for new threads | Writes the configured exact mask when the process has no Always affinity policy | Does not apply to active Game Mode sessions. A manual Current affinity stops default affinity from being applied to later threads of that process identity |
| Game Mode affinity | Once, on `processlasso-game`, before launch wrappers and the game are executed | Writes and verifies one exact launch mask; wrappers, the game, and their initial threads inherit it | Not continuously enforced. The game may later narrow or expand thread masks unless a matching Always affinity policy supplies an ongoing boundary |
| Processes → Current nice | Immediately | Writes the selected nice value to all currently visible threads | Allowed; only the matching Always nice field is suppressed after a successful manual write |
| Processes → Always absolute nice | At process and thread discovery, then according to rule enforcement | Applies the configured absolute nice value while retaining per-thread original values for restoration | External drift may be corrected while the policy remains active |
| Processes → Always offset nice | At process and thread discovery, then according to rule enforcement | Adds the offset to each thread's persisted original nice value and clamps the result to the configured floor and ceiling | The original baseline is persisted so restarts do not compound the offset; genuine external rebases become the new baseline |
| Game Mode nice | Once, on `processlasso-game`, before exec | Absolute policies use their value. Offset policies add to the launch wrapper's inherited nice value and clamp to their floor and ceiling | Inherited at launch but not continuously enforced; use an Always nice policy for ongoing enforcement |
| ProBalance | While enabled and load conditions qualify | Temporarily increases the nice value of eligible CPU-heavy background processes | Restores the captured original value after the cooldown. A failed restore leaves the process tracked as throttled so restoration can be retried |

All affinity writes are restricted to CPUs that are online at the time of the
write. A requested mask containing no online CPU cannot be applied. Threads can
appear or exit during any process-wide operation, so exact Current, default, and
Game Mode writes use bounded verification rather than claiming an unbounded
atomic update.

Manual overrides are field-specific. Changing Current nice does not disable an
Always affinity policy, and changing Current affinity does not disable Always
nice or I/O priority. Their runtime bookkeeping is cleared on process exit or
PID reuse; see [Runtime process-state ownership](runtime-state-ownership.md).
