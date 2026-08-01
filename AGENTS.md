# Repository agent guide

## Purpose and sources of truth

`House Ledger` is a local platform for importing personal financial activity and
household documents, normalizing them in PostgreSQL with dbt, and presenting
read-only views in Streamlit. It uses Python 3.12, PostgreSQL 17, dbt, and a
Bronze/Silver/Gold architecture.

- Use `README.md` for the detailed domain model, setup, and operator workflows.
- Treat the implementation and tests as the source of truth when documentation
  is stale. Call out the mismatch and update both when it is in scope.
- Keep this file focused on durable repository guidance. Task-specific goals and
  temporary decisions belong in the task prompt, not in `AGENTS.md`.
- Preserve the existing language of the surface being changed: code identifiers
  are English, while user-facing documentation and dashboard copy are generally
  Spanish.

## Architecture invariants

- Bronze preserves reproducible source records, ingestion metadata, stored
  documents, and versioned parser results. Do not hide destructive
  transformations inside Bronze ingestion.
- Silver normalizes movements, documents, invoices, due dates, line items, and
  credit-card transactions. Gold exposes query-ready movements, bills,
  documents, reconciliation candidates, card expenses, and shared expenses.
- A bill is an obligation, not a completed movement. Keep obligations and
  payments separate and reconcile them explicitly.
- PDF and statement files live in content-addressed storage outside PostgreSQL.
  The database stores paths, hashes, sizes, and traceability; do not put binary
  document contents in database tables.
- Imports and synchronization flows must remain idempotent. Preserve the current
  deduplication keys and source lineage when extending them.
- Streamlit reporting pages are read-only. Keep writes limited to explicit
  data-entry or maintenance interfaces and persist them in Bronze.
- Keep the legacy `raw` compatibility path working unless a task explicitly
  includes a migration and removal plan.
- External document downloads must remain restricted to trusted source
  endpoints, validate the response as a PDF, and enforce the configured size
  limit.

## Repository map

- `src/home_lab/cli.py`: CLI entry point and workflow orchestration.
- `src/home_lab/config.py`: environment-backed runtime configuration.
- `src/home_lab/database.py`: Bronze schema creation and compatibility migration.
- `src/home_lab/gmail/`: read-only Gmail client, Bronze repository, and pipeline.
- `src/home_lab/mercadopago/`: Reports API client, import/storage, and pipeline.
- `src/home_lab/siat/`: Rosario TGI client and pipeline.
- `src/home_lab/documents/`: PDF validation, content-addressed storage, parser
  registry, and source-specific parsers.
- `src/home_lab/dashboard/`: reporting queries and Streamlit pages, including
  explicit manual data-entry interfaces.
- `dbt/models/silver/`: normalization models.
- `dbt/models/gold/`: reporting and reconciliation models.
- `dbt/tests/` and model `schema.yml` files: dbt data-quality assertions.
- `tests/`: pytest unit and integration-style tests using local fakes/fixtures.
- `scripts/`: local development, deployment, backup, and maintenance commands.

## Change guidelines

- Inspect the relevant implementation, tests, and README section before editing.
  Prefer the smallest coherent change that satisfies the task.
- Keep HTTP clients, persistence, parsing, and orchestration separated according
  to the existing source-specific package structure. Avoid adding generic
  catch-all modules.
- Do not make live Gmail, Mercado Pago, or SIAT calls from automated tests. Use
  fakes or fixtures and test trust boundaries, malformed responses, and retries
  where relevant.
- When adding or changing a document parser, update the parser registry and add
  focused tests for both a supported document and an unrelated or invalid one.
  Preserve parser name/version traceability.
- When changing database structures, use forward-compatible, repeatable schema
  creation or migration. Do not drop or rewrite user data as a side effect of
  normal startup.
- When changing dbt models, preserve Bronze lineage, add or update schema/data
  tests, and check downstream Gold queries and dashboard expectations.
- When changing behavior or operator commands, update `README.md` in the same
  change.
- Add production dependencies only when the standard library and existing
  dependencies do not reasonably cover the requirement.

## Local setup and commands

Do not overwrite an existing `.env`. For a fresh checkout:

```bash
test -f .env || cp .env.example .env
docker compose up -d postgres
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/home-lab init-db
```

Useful commands:

```bash
.venv/bin/python -m pytest
.venv/bin/home-lab transform
docker compose up -d --build dashboard
docker compose config
```

`home-lab transform` runs `dbt build` with the repository's `dbt/` project and
profiles. It requires the configured local PostgreSQL instance.

## Validation expectations

- Run the most focused relevant pytest tests while iterating, then the full
  `.venv/bin/python -m pytest` suite for Python behavior changes.
- Run `.venv/bin/home-lab transform` for database, dbt, reconciliation, or
  dashboard-query changes.
- Run `docker compose config` for Compose changes.
- Run `bash -n` on every changed shell script.
- For dashboard changes, at minimum run the dashboard query tests and any
  relevant dbt build; exercise the page locally when the visual behavior matters.
- Documentation-only changes do not require runtime tests. Review rendered
  structure, verify commands against the repository, and run `git diff --check`.
- If a validation cannot run because services or credentials are unavailable,
  report exactly what was skipped and why.

## Sensitive data and external actions

- Never read, print, copy, or commit `.env`, `secrets/`, OAuth tokens, production
  access tokens, or files under `data/` unless the user explicitly puts a
  specific local artifact in scope. Minimize any output even then.
- Use `.env.example` and synthetic or sanitized fixtures for documentation and
  tests.
- Do not run authentication, production synchronization, report configuration,
  or other live external actions unless the user explicitly requests that action.
- Do not delete or rewrite local financial records, stored documents, database
  volumes, or credentials without explicit approval and a recovery plan.
- Keep secrets, account identifiers, personal management codes, document
  contents, and private financial values out of logs, exceptions, screenshots,
  patches, and commits.

## Git and worktree workflow

- Prefer the authenticated GitHub CLI (`gh`) for pull requests, Actions checks
  and logs, branch publication, and merges in this repository. Use a GitHub
  connector only when `gh` does not cover the required operation or the user
  explicitly requests the connector.
- For every task that will create, edit, rename, or delete repository files, work
  in a dedicated Git worktree. Read-only inspection, diagnosis, explanation, and
  status checks do not require a new worktree.
- Before editing, determine whether the current checkout is already a linked
  worktree. If it is, keep using it and do not create a nested or second worktree
  for the same task.
- When the task starts in the primary checkout:
  1. Inspect `git status` and preserve all existing user changes.
  2. Create a short, filesystem-safe task slug.
  3. Create a new branch named `codex/<slug>` and a linked worktree at
     `../worktrees/home-lab/<slug>`, based on the current `HEAD`.
  4. From the new worktree, run `scripts/init-worktree.sh` before any test,
     Compose, or application command. This creates the worktree's isolated
     `.env`, `.venv`, ports, Compose project, database volume, and data paths.
     Do not copy another checkout's `.env` or run Compose with improvised
     settings.
  5. Perform every file modification and all task-specific validation from that
     worktree. Do not modify the primary checkout.
- `scripts/dev-up.sh` starts isolated PostgreSQL and dbt by default; add `--full`
  only for dashboard work. Use `--snapshot` only when representative production
  data is required. Treat that database as sensitive production-derived data:
  never print, export, commit, or copy its contents into fixtures or logs.
- Choose a unique slug if the intended branch or directory already exists.
- Do not copy, stash, reset, clean, or otherwise alter uncommitted changes from
  the primary checkout unless the user explicitly asks.
- Do not commit, push, or open a pull request unless the user requests it.
- Do not automatically remove the task worktree when finished. In the final
  response, report its absolute path and branch name so it can be opened in Zed,
  reviewed, merged, or removed later.
- If the user explicitly asks to work in the current checkout, that request
  overrides this workflow for that task.

## Completion checklist

- Review `git diff` and `git status`; keep unrelated changes out of the task.
- Run the validation appropriate to the changed files.
- Summarize the behavior and guidance changed, validation results, and any
  remaining risks or skipped checks.
