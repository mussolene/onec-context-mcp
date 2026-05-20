---
name: oacs-repo-memory
description: Use OACS/ACS selectively during substantial repository work to build governed context only when project memory, prior decisions, policy, evidence, or checkpoints matter; record command results as evidence and checkpoint iterations.
---

# OACS Repo Context

This is a Cursor-facing client skill for repositories that use OACS/ACS. It is
not part of the OACS standard.

## Start

1. Define task scope and acceptance criteria.
2. Check current repository state:

```bash
git status --short
acs status --json
```

3. Ask the reference context gate before building context:

```bash
acs context gate --intent repo_development --scope project --task "<task>" --json
```

Treat `decision=skip` as permission to proceed from visible files and the user
request. Treat `decision=build` as the signal to build context.
4. Build context only when the gate says `build` or prior memory/evidence
   clearly matters:

```bash
acs context build --intent repo_development --scope project --json
```

If context build fails because keys are not initialized or unlocked, continue
only with public records and file inspection unless the user explicitly wants
memory decryption setup.

## During Work

- Run project tools directly (`pytest`, `npm test`, `flutter test`, CI checks,
  deployment commands, retrieval tools, etc.).
- Record canonical results:

```bash
acs tool ingest-result \
  --tool-id local_verification \
  --tool-name local_verification \
  --tool-type external \
  --status completed \
  --input '{"commands":["<command>"]}' \
  --output '{"status":"PASS","summary":"<short factual summary>"}' \
  --json
```

- Inspect evidence refs that matter:

```bash
acs evidence inspect <ev_...> --json
```

- Turn evidence into durable memory only after review. Keep D1 episodes cheap;
  D2+ facts/procedures and D3-D5 patterns need explicit evidence-backed review.

## Finish

1. Run current verification.
2. Run leak/secret checks appropriate for the repository.
3. Ingest both results as evidence.
4. Add a checkpoint:

```bash
acs checkpoint add \
  --task "<task-id>" \
  --summary "<what changed and why>" \
  --next "<next step or Done>" \
  --evidence <ev_...> \
  --json
```

5. Final response must name checks run, residual risks, and any OACS blocker.

## Guardrails

- OACS is not the tool orchestrator.
- Do not prepend OACS context unconditionally. Use `acs context gate` or an
  equivalent explicit decision before context build.
- Standalone tool evidence is not projected into context unless a reviewed
  memory references it.
- Preserve attribution roles in distilled memory.
- Never read, print, or commit `.agent/oacs/key.json`,
  `.agent/oacs/unlocked.key`, `.agent/oacs`, `.oacs`, key material,
  passphrases, local databases, or private agent state.
