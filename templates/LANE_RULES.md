# Lane rules — lineage

The defaults written by `factory init` are not style preferences; each
encodes an incident from the source lane. Read before editing.

| # | Rule | Encodes |
|---|------|---------|
| 0 | one ticket at a time; claim + queue update in the same commit as the work | parallel-claim races; "who was driving?" forensics |
| 1 | RED-first: negative leg shown RED before GREEN is trusted | GREEN-only gates that could not fail were trusted for weeks |
| 2 | receipt per rung with a "what this does NOT prove" section | self-graded claims; proof-limiting sections caught scope inflation |
| 3 | pins frozen unless a ticket upgrades them | silent dep drift moving behavior under a running lane |
| 4 | never absorb pre-existing failures into a gate | a 12-failure baseline hid inside "known issues" until counted and named once |
| 5 | WAKE DISCIPLINE: every tick ends with a commit | the lane's first idle tick left the digest unchanged; the next tick suppressed; lane silently dead |
| 6 | package installs: ASK + same-commit record; additive only | `pip --user` + sudo mixups; provenance lost when installs happened off-record |
| 7 | COMMIT PER SUB-STEP | an iteration cap arrived mid-multipart change; uncommitted sub-steps were orphaned |
| 8 | GATE TIMEOUTS: explicit timeout below scheduler kill threshold | a bare long suite wedged the tick; the scheduler killed it; nothing recorded why |
| 9 | COMMIT SCOPE: enumerate paths, never `git add -A` | unrelated dirty files swept into lane commits; provenance destroyed |

Deliberately NOT in the defaults: the source lane's rule 9 (z_order tie
order) — domain-specific, lives in that lane's queue file, not the product.

Editing rules: append, don't reorder (the observer hashes the rules list;
reordering churns every downstream hash). The observer's `watch_rules`
config locates rules by CONTENT substring, never index — moving a rule
never breaks a watch.
