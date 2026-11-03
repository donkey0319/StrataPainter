# Agent workflow

These instructions apply to every agent editing this repository.

- The owner authorizes agents to commit and push completed project changes as a standing instruction. After each coherent task that changes files, run appropriate focused checks, inspect the diff, create a descriptive commit, and push the current branch to its configured upstream. If no upstream exists, publish the current branch to origin and establish tracking. Do not ask for routine commit/push confirmation.
- Inspect Git status before editing. Preserve unrelated staged, unstaged and untracked work. Stage only your task's changes unless the owner explicitly asks to include all pending changes. Do not reset, clean, force-push, rewrite history, or discard other agents' work.
- Keep tests and generated evidence local. Never force-add tests/, .artifacts/, environments, caches, credentials, or generated builds. The tests/ directory must remain ignored and absent from the Git index; do not restore public test CI.
- For StrataPainter milestone work, read docs/IMPLEMENTATION_STATUS.md and the relevant part of docs/STRATA_PAINTER_IMPLEMENTATION_PLAN.md. Use one agent, targeted reads, concise logs, focused checks and one final regression pass. Update relevant implementation/qualification documentation.
- The known low-flow feature assertion remains a documented baseline failure. Do not weaken assertions or change reference images to hide it. Report new failures accurately and fix failures caused by the task before committing.
- Before committing, check the staged file inventory and whitespace, and ensure private files are excluded. After pushing, verify the remote branch matches the local commit and report the commit ID and any remaining limitations.
- If validation, commit or push is blocked, retain the work and explain the concrete blocker. Do not claim an unpushed commit is published. Never create a release/tag or bypass an approval/security rejection merely to satisfy this workflow.
