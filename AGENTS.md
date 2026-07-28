# Repository workflow

## Worktree isolation

- For every task that will create, edit, rename, or delete repository files, work
  in a dedicated Git worktree. Read-only inspection, diagnosis, explanation, and
  status checks do not require a new worktree.
- Before editing, determine whether the current checkout is already a linked
  worktree. If it is, keep using it and do not create a nested or second
  worktree for the same task.
- When the task starts in the primary checkout:
  1. Inspect `git status` and preserve all existing user changes.
  2. Create a short, filesystem-safe task slug.
  3. Create a new branch named `codex/<slug>` and a linked worktree at
     `../worktrees/home-lab/<slug>`, based on the current `HEAD`.
  4. Perform every file modification and all task-specific validation from that
     worktree. Do not modify the primary checkout.
- Choose a unique slug if the intended branch or directory already exists.
- Do not copy, stash, reset, clean, or otherwise alter uncommitted changes from
  the primary checkout unless the user explicitly asks.
- Do not automatically remove the task worktree when finished. In the final
  response, report its absolute path and branch name so it can be opened in Zed,
  reviewed, merged, or removed later.
- If the user explicitly asks to work in the current checkout, that request
  overrides this workflow for that task.
