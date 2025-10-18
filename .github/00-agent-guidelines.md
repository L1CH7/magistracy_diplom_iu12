# Agent Guidelines (Global)

These preferences apply across my projects when using the agent mode. Treat this as the default unless a repository contains overrides.

- Keep responses concise and skimmable; focus on actions and artifacts.
- Always create runnable scripts/files instead of dumping long code into the terminal.
- Prefer `.agent_dir/` for your own helper scripts, outputs, and temp artifacts.
- When you need to run Python, create/modify a script and then run it; avoid huge inline Python one-liners.
- Track progress with a TODO list. Update item statuses as you go.
- Favor config-driven, reproducible experiments (YAML/TOML/JSON), commit minimal diffs.
- After creating runnable code, run a quick test and report PASS/FAIL for build/lint/tests when applicable.
- Be explicit about assumptions and note any unresolved questions.
- Propose small, high-value adjacent improvements after completing the main ask.
- When running commands, assume zsh and Linux; provide copyable commands in fenced blocks, one per line.

## Data handling
- Never print sensitive data. For large files, summarize.
- If a file is binary (e.g., .docx), extract only text needed.
- Cache lightweight EDA reports to `.agent_dir/out`.

## Networking and compute
- If VPN/SSH disrupts the chat channel, propose split-tunnel/policy-routing or alternatives (Colab/Runpod).
- Prefer CPU-friendly baselines locally; defer GPU training to remote compute.

## Experimentation
- Provide at least two non-LLM methods for baselines and one LLM method, compare all with a clear table.
- Use proper validation: stratified split, cross-validation when sample size is small, and report F1/ROC AUC.
- Save seeds and configs; enable deterministic runs when feasible.

## Files and folders
- Put helper scripts in `.agent_dir/`.
- Repository-level instructions live under `.github/` with `00-` prefix for prioritization.
- Add short READMEs for how to run things when new tools are added.

## Security
- Do not exfiltrate secrets; avoid hardcoding tokens.
- Mask PII in logs and artifacts.
