# Codex: OACS consumer pack

`AGENTS.md` is the native Codex instruction surface and already contains the
OACS / ACS Repository Workflow section installed from `open-agent-context`.

This directory keeps the optional Codex-specific OACS runtime skill from
`../open-agent-context/examples/skills/codex_oacs_runtime` as a tracked repo
example. It is not part of the OACS portable standard; it is a removable Codex
adapter for context rebuilds, evidence, checkpoints, and explicitly requested
subagent coordination.

## What Is Tracked

- `codex_oacs_runtime/SKILL.md` - Codex-facing workflow instructions.
- `codex_oacs_runtime/skill.json` - skill manifest for the `acs skill run`
  reference implementation.
- `codex_oacs_runtime/scripts/repo_memory.py` - script adapter used by
  `skill.json`.

## Local Use

The repo-native baseline is automatic for Codex through `AGENTS.md`.

If you want to install the optional skill into your local Codex skills folder,
copy it explicitly:

```bash
mkdir -p ~/.codex/skills/codex_oacs_runtime
rsync -a --delete docs/codex-examples/codex_oacs_runtime/ ~/.codex/skills/codex_oacs_runtime/
```

If you want to use it through the OACS reference CLI from the repository copy,
run it by path or sync it into the OACS skill registry according to your local
`acs` setup.

## Safety

Do not commit `.agent/oacs/`, `.oacs/`, key material, passphrases, local OACS
databases, or private agent state. The repository `.gitignore` protects the
standard local OACS state directories.
