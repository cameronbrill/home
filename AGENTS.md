# AGENTS.md

## Worktree safety

- The worktree may contain intentional in-progress changes. Leave unrelated dirty files alone; never revert, delete, or commit them unless explicitly asked.

## Quality gate

- `mise run check` runs format, typecheck, lint, and tests. Run it before claiming work is done.
- Targeted runs: `mise run test`, `mise run lint:ruff`, `mise run typecheck`.

## CI and deploys

- CI is RWX (`.rwx/main.yml` → `ci`, `build-image`, `publish-image`, `deploy`). GitHub Actions is retired; do not add workflows.
- The `.rwx/main.yml` CLI trigger is retained for debugging. Use `rwx run .rwx/push.yml --target ci` for checks; `rwx run .rwx/main.yml --target deploy` is the explicit production path.
- Fly production is read-only unless the user authorizes a change: logs/status only; no deploys, secret changes, or machine teardown on your own initiative.
- Prefer one active machine for `home-dfqtra`; create extra machines only for explicit probes and remove them after.

## Roborock session recovery

- Password login fails with code `2031` (two-step validation). Recovery is the v4 email-code flow: `request_code_v4()` then `code_login_v4()` on the same `RoborockApiClient` (from `roborock.web_api`), validate with `_get_home_id()`, persist `as_dict()` as single-line JSON.
- Stale sessions surface as `2010` from `getHomeDetail`; replace the RWX vault value and let `deploy` stage it via `flyctl secrets import`.

## Fly probe pitfall

- Disposable `flyctl machine run` probes must pass `ROBOROCK_CANDIDATE_SESSION` and remap it to `ROBOROCK_SESSION` in the probe entrypoint. An app secret named `ROBOROCK_SESSION` is not overridden by `--env`, so same-name probes can show a false `2010`.

## Secrets

- Never print, echo, or commit session JSON, tokens, `local_key`, or other credentials. Write temp files mode 600 and delete them after use; keep them out of logs and diffs.
