# TICKET — r6: allowlist glob patterns

## Charter
`- Rung r6` (v0.4.0). `resolve_allowlist()` matches entries as exact paths or `path/` prefixes only. Lanes keep wanting `*.lock`, `audits/*.md`, `*.local.json` — today each new noise file is a config edit that itself dirties the tree and wakes the digest.

## Goal
Extend allowlist entries containing glob metacharacters (`*?[`) to match via `fnmatch.fnmatch` against the full relative path, while keeping exact/prefix semantics for entries without metacharacters (zero behavior change for existing configs). `scoped_dirty_rows()` applies the same matcher. Observer and digest share it — one implementation, both surfaces.

## Constraints
- Existing lanes' fingerprints must not change: regression-test that a config without globs produces identical digests before/after.
- A glob matching a file the digest NEEDS (queue_state.json, ROADMAP ladder path) must be safe: document that allowlisted files still move the fingerprint via their dedicated hash channels (QUEUE/TICKETS/LADDER are hashed independently of TREE).
- RED-first in the claim commit (rule 0); receipt with paired commands/outputs; both required sections.
