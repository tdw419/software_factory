# Wiring the factory to Hermes cron

Two legs, exactly like the source lane: a tick leg (LLM, change-gated) and
an observer leg (mechanical, pure script). Keep them separate — the
observer must not depend on the LLM being awake.

## Leg 1 — tick (agent mode)

    # ~/.hermes/cron — agent-mode job
    every: 30m
    workdir: /path/to/your/repo
    prompt: |
      Run `python3 -m software_factory tick` in the current repo.
      Read the exit code:
        0            -> report one line ("WAKE <rung>" or "SUPPRESSED"), nothing else
        4 / 5 / 6    -> read .factory/decision_log.jsonl tail, diagnose the
                        recorded problem, DO NOT hand-fix the builder's work;
                        the lane retries or parks itself
      Never edit .factory/decision_log.jsonl (append-only) and never commit
      on the lane's behalf unless the tick asked you to (it never does).

Notes from the source lane:
- bare `15m` in Hermes cron is ONE-SHOT; use the interval form.
- keep the prompt short: cron update flows have mangled long prompts.
- if the lane parks (exit 6), the correct response is diagnosis, then
  `factory tick --force` after the fix — the park exists to stop
  hot-looping, not to be cleared blindly.

## Leg 2 — observer (monitor_script, no LLM on quiet)

    # ~/.hermes/cron — monitor_script job
    every: 20m
    monitor_script: /abs/path/factory_observe.sh
    workdir: /path/to/your/repo

    # factory_observe.sh — stdout is the change-gating payload
    #!/bin/sh
    cd /path/to/your/repo
    exec python3 -m software_factory observe

The observer prints a STABLE state tuple (no timestamps). Hermes wakes the
agent only when the output changes; unchanged output = a no-op tick that
costs nothing. `factory observe --log-dir audits/` additionally appends a
timestamped snapshot per change — run that variant from a plain cron if
you want the audit file.

## Optional leg 3 — LLM observer (judgment)

Give a low-frequency agent job the prompt in
`.factory/templates/OBSERVER_PROMPT.md`. It reads the mechanical
observer's log + the queue + receipts and writes a dated OBS entry:
priors, heartbeat, findings (re-executed, never inherited), corrections
against itself, coverage census. The census rule matters: a heartbeat
cannot distinguish "did not fire" from "fired and died before writing" —
count run directories in `.factory/runs/`, not log headings.
