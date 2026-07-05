---
name: lmh
description: Use when the user wants an answer from local/offline/private models, mentions lmh, Ollama, 本地模型, 離線模型, or asks to draft/translate/summarize something cheaply without cloud tokens.
---

# lmh — Local Ollama Multi-Model Harness

<!-- Install: copy this file to ~/.claude/skills/lmh/SKILL.md (one-time per machine), then restart the Claude Code session. -->

Run in PowerShell: `lmh ...`. If `lmh` is not found (fresh shell / Bash), call it by full path instead — PowerShell: `python "$env:USERPROFILE\.local_model_harness\harness.py" ...`; Bash: `python "$USERPROFILE/.local_model_harness/harness.py" ...`. Command-not-found is a PATH issue, not a harness failure.

## Commands

- `lmh ask "<question>"` — one local call, auto-routed (fast/general/coder/reasoner). Auto-routing is the default choice; only force `--mode` if it clearly misroutes.
- `lmh ask --mode code|reasoning|quick|general --strength review "<task>"` — force a route; `review` adds a critique by a second local model.
- `lmh doctor` — health check. Run when a harness call errors (connection refused, missing model). If doctor fails, report its output and stop.
- `lmh eval` — re-score the model pool after any model change.

## Rules

- The harness has no conversation memory: pack all needed context into ONE self-contained prompt.
- Local models are 4B–8B drafting tools. Verify code and factual claims yourself before relaying; never present lmh output as verified.
- Attribute results to the local model shown in the `Calls:` line of the output.
- Config lives in `~\.local_model_harness\profiles.json`; routing/upgrade rules in `~\.local_model_harness\docs\MODEL_SELECTION.md`.
