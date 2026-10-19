# software_factory

A standalone autonomous builder lane. Point it at any git repo, drop in
tickets, wire one cron job, and a coding agent of your choice lands rungs
through change-gated ticks with receipts, an append-only decision log, and a
mechanical second checker.

Zero dependencies. Python >= 3.10 stdlib only.

This is not a novel design — every mechanism here is distilled from
production lanes (geometry_os + the Visual Audio compositor lane, 2026-10)
that ran autonomously for weeks: 353 ticks and 5,843 decision records on
the largest, which absorbed 405 recorded failures, 81 gate operations, 16
lock contentions and 3 discipline violations while still landing rungs. See
`templates/LANE_RULES.md` for the mechanism-by-mechanism lineage.

## Install

Nothing to install:

    python3 software_factory/cli.py --help          # direct
    python3 -m software_factory --help              # module
    pip install -e . && factory --help              # if you want `factory` on PATH

## Quickstart

    cd my-project
    factory init --lane compositor --verify-cmd "pytest -q" \
                 --builder-cmd "hermes chat --query-file {prompt} --oneshot --in {repo} --yolo"

    # author a ticket
    cp .factory/tickets/_TEMPLATE.md .factory/tickets/t1_drag.md
    $EDITOR .factory/tickets/t1_drag.md

    # register it on the queue
    factory ticket add --id t1 --title "drag plumbing" --ticket .factory/tickets/t1_drag.md

    # one tick by hand (digest gate makes repeats free)
    factory tick          # -> WAKE t1: builder ok, verify pass, head abc -> def
    factory tick          # -> SUPPRESSED no_change   (parked is not stalled)
    factory status

Then wire `factory tick` to any scheduler (see below) and it only spends
tokens when the repo actually changes.

## Concepts

### The tick (change-gated)

Each tick hashes a stable fingerprint: HEAD + queue_state + tickets + tree
dirt (minus the churn allowlist) + ladder status lines. Unchanged
fingerprint -> the tick is a cheap no-op. Changed -> dispatch.

### Scoped lanes (watch_paths, r8)

The HEAD part is the last commit TOUCHING the lane's `digest.watch_paths`
(lane-relative pathspecs; default `["."]` = the lane's own subtree — for a
repo-root lane this is exactly the old repo-global HEAD, byte-identical).
A lane nested inside a bigger repo — or sharing one with another lane's
bookkeeping (e.g. an incumbent `.builder_queue/`) — scopes HEAD so foreign
commits don't wake it:

```json
{ "digest": { "watch_paths": ["systems", "docs"] } }
```

No commit in history touches the watch paths -> the HEAD part is the
stable sentinel `NONE` (the scope's first commit then wakes the lane).
Git failure -> DEGRADED, never dispatches.

### Co-tenanted lanes (kernel guard attribution, r9)

The kernel guard attributes churn the same way the digest attributes HEAD:
to THIS lane's tick, not to the repo's ambient state.

- **Tick post-check**: kernel surfaces = committed kernel touches in
  `head_before..head_after` plus the working-tree DELTA (dirt after minus a
  pre-dispatch baseline). Pre-existing dirt — the incumbent's bookkeeping —
  is never a violation.
- **Observer**: kernel-guard reports committed kernel touches since the
  lane's creation head (stateless tuple stays stable under co-tenant churn).
- **Watch-scope filter**: kernel churn OUTSIDE the lane's `digest.watch_paths`
  is co-tenant territory on both surfaces and never attributed here. A lane
  guarding `.builder_queue/` while watching `["systems"]` gets a stable
  `kernel_guard=OK`; a lane whose kernel surfaces sit inside its scope
  (e.g. sf_next) keeps the full guard.

Failure semantics, learned the hard way:

- builder fails or verify RED -> the fingerprint is NOT advanced, so the
  next tick RETRIES; after 3 consecutive builder/gate failures the lane PARKS
  itself (exit 6) instead of hot-looping. Clear with `factory tick --force`
  after fixing the cause.
- transient failures (degraded git, builder timeout) increment
  `transient_failures` and retry on the next tick without advancing the
  3-strike park counter.
- overlapping ticks are guarded by a non-blocking `fcntl.flock` on
  `.factory/tick.lock` (exit 8).
- builder returns 0 but commits nothing -> WAKE DISCIPLINE violation,
  recorded loudly (a tick that ends without a commit leaves the digest
  unchanged and the lane silently dies at its next idle tick).
- builder leaves a rung `IN_PROGRESS` with no `claimed_by` -> QUEUE
  DISCIPLINE violation (`next_actionable` only resumes claimed rungs, so an
  unclaimed `IN_PROGRESS` rung would otherwise orphan the lane).
- git unreadable -> suppressed, never dispatched on unknown state.
- churn allowlist: decision_log/state/runs/asks/pending_gate/tick.lock are
  excluded from the fingerprint, or the lane wakes on its own heartbeat
  forever.

### Tickets and receipts

A ticket declares stages: probe (disruption 0) -> RED -> GREEN -> receipt.
The RED stage must show the verification gate failing on the unfixed state
before GREEN is trusted. The receipt pairs commands and outputs in the same
fence and carries mandatory `## What PASS proves` and
`## What this does NOT prove` sections. The tick refuses a builder exit 0
if the receipt is missing or lacks either required section.

Lifecycle updates can be performed via CLI (refusing prose commit handles at
the source and recording `decision_log.jsonl` provenance):

    factory ticket set t1 --status IN_PROGRESS --claimed-by hermes
    factory ticket set t1 --status LANDED --commit $(git rev-parse HEAD)

### The decision log (append-only)

`.factory/decision_log.jsonl` — one JSON object per line, raw UTF-8.
Every wake, failure, GO, abort, and refusal lands here. Agents never
rewrite it. Raw UTF-8 is deliberate: `json.dumps` default escapes em dashes
as `\u2014`, and an escaped phrase once failed a byte-exact GO match.

### The GO gate (disruptive operations)

Anything disruptive (scanout takeover, bulk deletion, force push) is staged:

    factory gate arm --kind scanout --phrase "GO scanout — laptop" -- ./takeover.sh --target eDP-1
    factory gate fire "GO scanout — laptop"       # byte-exact: no strip, no normalization
    factory gate abort --kind scanout --reason "wrong target enumerated"

Preflight refuses a second arm while a gate is already pending, and refuses a
second fire while a GO is un-aborted (spend accounting: 2 GO + 2 aborts = 0
unspent). Wrong phrases are refused and logged, the gate stays armed. If the
authorized op times out, `fire` records exit `124` and disarms cleanly.

### The observer (second checker)

    factory observe                                # stable state tuple on stdout
    factory observe --log-dir audits/              # appends only on change

Feed it to a separate cron leg. It classifies LANDED commit handles
(`RESOLVED` / `BROKEN` / `PROSE` / `MISSING`), locates named rules by content
(never by index), checks receipts exist and contain required sections
(`receipts_missing`, `receipts_incomplete`), surfaces armed gates
(`gate_armed`, `gate_armed_stale=yes/no`), and watches the tick heartbeat
(with `observer.heartbeat_stale_after_min` armed, freshness is the newest of
`.factory/runs/` mtime and `.factory/state.json:last_tick_ts`, so `WAKE
no_actionable` and `degraded` ticks count alongside `suppressed` and builder
dispatches — r5/r7).
It never writes the repo. Pair it with the LLM observer prompt in
`.factory/templates/OBSERVER_PROMPT.md` for a judgment leg.

### Self-diagnosis (`diagnose`, s1)

    factory diagnose                               # deterministic findings + findings=<n>

A read-only pattern counter over the lane's own decision history (same trust
tier as the observer: pure function, zero LLM calls, zero writes). It scans
`decision_log.archive.jsonl` + `decision_log.jsonl` deduplicated by `ts`
(compaction-proof across `factory log compact`), buckets `tick_failed`,
`gate_refused`, and `rung_demoted` records into deterministic signatures
(`failure_class:<pattern>`, `violation:<kind>`, `stall`, `parked`), and
suppresses signatures covered by `DRAFT`/`OPEN`/`IN_PROGRESS` rungs (or
`LANDED` rungs whose `landed_at` is at/after the newest cited evidence;
post-fix recurrences re-fire).

### Human gate (ASKs)

    factory ask create --subject "packages" --question "install scipy?" --options "y/n"
    factory ask list
    factory ask answer ASK-20261017 --answer "YES — scipy"

The operator answers via `factory ask answer` (which flips `status: ANSWERED`,
fills the Answer block, and appends an `ask_answered` provenance record to
`decision_log.jsonl`) or by editing the file directly. Files are the queue.

## Scheduler wiring

Any cron that can run a command works. `factory tick` exits 0 on
ok/suppressed, 4 verify RED, 5 builder failed, 6 parked, 7 degraded (when
forced), 8 locked (concurrent tick running).

Hermes Agent example (`~/.hermes/cron`): agent-mode job, every 30 min,
prompt: "run `factory tick` in <repo>, read the exit code, act per
README". For the observer use a monitor_script job with
`factory observe` — its stable output is exactly the change-gating
contract. Full walkthrough: `templates/HERMES_CRON_WIRING.md`.

## Exit codes (tick)

    0  ok / suppressed / nothing actionable
    4  verify gate RED (or verify misconfigured while required)
    5  builder failed (or missing/incomplete receipt, wake/queue discipline violation)
    6  parked (clear with --force after fixing the cause)
    7  degraded git state encountered on --force
    8  locked (another factory tick is currently running)

## The rules (shipped as defaults)

`factory init` writes the 10 general lane rules into queue_state.json:
one ticket at a time, RED-first, receipts with proof-limiting sections,
frozen pins, no absorbing pre-existing failures, WAKE DISCIPLINE,
operator-approved package installs, commit per sub-step, explicit gate
timeouts, enumerated commit scope. Edit them per lane — but read
`templates/LANE_RULES.md` first: each encodes a specific incident.

## Layout

    .factory/
      config.json           lane config (builder cmd, verify cmd, timeouts, allowlist)
      queue_state.json      rungs, claims, rules
      decision_log.jsonl    append-only audit
      tickets/              ticket files (committed)
      receipts/             receipts (committed)
      runs/                 per-tick dispatch artifacts (gitignored)
      asks/                 human-gate queue (committed)
      state.json            tick counters + last fingerprint (gitignored)
      tick.lock             flock concurrency guard (gitignored)
      templates/            prompt templates (committed)

Commit `.factory/` (except `runs/`, `state.json`, `pending_gate.json`,
`tick.lock` — the init gitignore handles those). The queue and log ARE the
lane's memory.

## Provenance

Distilled 2026-10-17 from the geometry_os compositor lane: rung1_monitor.py
(digest gating), compositor_observer_monitor.py (mechanical second checker),
QUEUE_STATE.json + 11 lane rules, gate_b_go.sh (GO/abort spend accounting),
RUNG1_TICKET.md (ticket anatomy), and the lane's failure record (HEAD.lock
races, fetch-storm false wakes, escaped-em-dash GO mismatch, watchdog
self-wake loops, silent stalls from idle-tick suppression).

Measured 2026-10-19, so the claim above is checkable: the Visual Audio
lane's decision log (`visual_audio/.builder_queue/decision_log.jsonl`) holds
5,843 records spanning 2026-10-01 → 2026-10-13 in-log — ticks 1–303 in the
log, 353 by 2026-10-18 in git — including 405 failure-shaped records, 81
gate operations, 16 lock contentions, 3 discipline violations and 2 parks,
with the lane still landing rungs throughout. The geometry_os distillation
artifacts live in `geometry_os/geometry_os/.builder_queue/`:
`rung1_monitor.py`, `QUEUE_STATE.json` (11 rules verified),
`RUNG1_TICKET.md`.
