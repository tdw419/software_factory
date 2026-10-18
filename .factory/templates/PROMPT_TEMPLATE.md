# Lane tick — {lane} — rung {rung_id}{resuming}

You are the builder for this lane tick. Repository: {repo}
{resuming_note}
## Ticket
{ticket_body}

## Lane rules (binding)
{rules}

## Builder contract
- Claim the rung FIRST: set status=IN_PROGRESS, claimed_by, claimed_at in
  .factory/queue_state.json (or via `factory ticket set {rung_id} --status IN_PROGRESS --claimed-by <agent>`),
  IN THE SAME COMMIT as your first work commit.
- COMMIT PER SUB-STEP: never hold finished sub-steps in the tree.
- COMMIT SCOPE: enumerate exact paths; never `git add -A` or bare `git add .`.
- RED-first: prove the verification gate can fail before trusting GREEN.
- Write the receipt at {receipt_path}: commands and outputs PAIRED in the
  same fence, plus an explicit "What this does NOT prove" section.
- Land the rung in queue_state.json: status=LANDED, landed_at, and
  commit=<the real sha> (or `factory ticket set {rung_id} --status LANDED --commit <sha>`).
  NEVER the prose "this commit".
- End the tick with a commit even if only decisions landed (infra_notes).
