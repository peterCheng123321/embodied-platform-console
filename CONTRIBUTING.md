# Contributing

The intent: nobody pushes commits straight to `main`. Every change lands through
a reviewed pull request that passes CI. This is **enforced server-side only after
an admin applies the ruleset** (see Admin notes) — until then the rules below are
convention plus a local guard, not a hard lock.

## One-time setup

```bash
scripts/install-hooks.sh    # activates the pre-push guard for this clone
```

`core.hooksPath` is per-clone and is not copied by `git clone`, so run this once
after cloning. It blocks accidental `git push` to `main` **locally**. It is
best-effort convenience only: it can be skipped (`git push --no-verify`) and a
fresh clone that never runs it has no local guard at all. The load-bearing
control is the server-side ruleset, not this hook.

## Shipping a fix

Make your change in the working tree on `main`, then:

```bash
scripts/fix-push.sh <slug> "<commit / PR title>"
# e.g.
scripts/fix-push.sh queue-retry-log "fix(queue): log swallowed projection error"
```

`fix-push` runs a **fast subset** of CI's correctness gates locally (structural
audit, JS syntax, **ruff lint**, backend JSON-store tests, whitespace/bytecode
hygiene) before touching git, then cuts `fix/<slug>`, commits, pushes the branch, and opens a PR
into `main`. It never writes to `main`. The subset is a quick smoke check — **CI
is authoritative**: the Postgres and Docker jobs run only on the PR.

A PR merges once it has **one approving review** and the required CI checks are
green.

### Required-to-merge checks

These job names (from `.github/workflows/ci.yml`) gate every PR — keep the list
in `.github/rulesets/main-protection.json` in sync if you rename a job (a
mismatched name never goes green and blocks all merges):

- `repository hygiene`
- `static frontend and design audit`
- `lint (ruff)`
- `backend tests (Python 3.11, JSON store)`
- `backend tests (Python 3.13, JSON store)`
- `backend tests (Postgres repository)`
- `docker image build`
- `docker runtime smoke`

## Admin notes

The real lock is the server-side GitHub **ruleset**, not the local hook.

**Repository admins are exempt from the flow entirely**, not just for emergency
direct pushes: with `bypass_mode: always`, an admin can also open a PR and merge
it with **zero approvals and skipped/red CI** (`gh pr merge --admin`). Use the
bypass sparingly; everyone outside the admin role must go through review + green
CI. The local hook's `--no-verify` only skips the local guard for *anyone* — it
is not an authorization; non-admins are still stopped server-side.

### Applying the ruleset (admin, one-time — do this to turn enforcement on)

Changing repository access controls is the admin's action. Until this runs,
`main` is **not** protected server-side. Apply the tracked ruleset:

```bash
gh api --method POST \
  -H "Accept: application/vnd.github+json" \
  repos/peterCheng123321/embodied-platform-console/rulesets \
  --input .github/rulesets/main-protection.json
```

Then **verify it is live** (expect a `pull_request` rule and the 7 required
checks):

```bash
gh api repos/peterCheng123321/embodied-platform-console/rulesets \
  --jq '.[] | select(.name=="main protection") | {id, enforcement}'
gh api repos/peterCheng123321/embodied-platform-console/rulesets/<id> \
  --jq '.rules[].type'
```

To update it later, PUT the same file to `.../rulesets/<id>`. Or apply it in the
UI: **Settings → Rules → Rulesets → New branch ruleset**, target the default
branch, and add the rules above.
