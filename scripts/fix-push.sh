#!/usr/bin/env bash
#
# fix-push.sh — the universal issue-fix push command.
#
# Ships a fix the safe way: never to main directly. From an up-to-date main with
# your fix in the working tree, this:
#   1. stages your change and runs a fast subset of CI's correctness gates
#      (structural audit, JS syntax, backend JSON-store tests, whitespace/bytecode
#      hygiene) — fail-fast, before creating any branch. CI is authoritative on
#      the PR; the Postgres and Docker jobs run there, not locally.
#   2. cuts a fix/<slug> branch, commits your changes,
#   3. pushes the BRANCH (not main) and opens a pull request.
#
# main is then reachable only through review + green CI (see the GitHub ruleset
# in .github/rulesets/main-protection.json and CONTRIBUTING.md).
#
# Usage:
#   scripts/fix-push.sh <slug> "<commit / PR title>"
#
# Example:
#   scripts/fix-push.sh queue-retry-log "fix(queue): log swallowed projection error"
#
set -euo pipefail

die()  { printf '\033[31mfix-push: %s\033[0m\n' "$*" >&2; exit 1; }
note() { printf '\033[36mfix-push:\033[0m %s\n' "$*"; }
ok()   { printf '\033[32mfix-push:\033[0m %s\n' "$*"; }

# --- args -------------------------------------------------------------------
[ "$#" -eq 2 ] || die "usage: scripts/fix-push.sh <slug> \"<commit / PR title>\""
SLUG="$1"
MESSAGE="$2"
[ -n "$MESSAGE" ] || die "commit/PR title must not be empty"
# Safe branch component: lowercase alnum plus . _ - , no leading punctuation.
[[ "$SLUG" =~ ^[a-z0-9][a-z0-9._-]*$ ]] \
  || die "slug must match ^[a-z0-9][a-z0-9._-]*\$ (got: '$SLUG')"
BRANCH="fix/${SLUG}"

# --- locate repo, normalise cwd --------------------------------------------
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "not inside a git repository"
cd "$ROOT"

# --- preflight --------------------------------------------------------------
command -v gh >/dev/null 2>&1 || die "the GitHub CLI 'gh' is required (https://cli.github.com)"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated — run: gh auth login"

CURRENT="$(git symbolic-ref --quiet --short HEAD)" \
  || die "detached HEAD — check out main and make your fix there first"
if [ "$CURRENT" != "main" ]; then
  case "$CURRENT" in
    fix/*) die "you are on '$CURRENT'. If a previous run was interrupted, finish it with:
    git push -u origin ${CURRENT} && gh pr create --base main --head ${CURRENT} --fill
  Otherwise switch back to main and re-run." ;;
    *)     die "run this from 'main' with your fix in the working tree (currently on '$CURRENT')" ;;
  esac
fi

[ -n "$(git status --porcelain)" ] \
  || die "no changes to ship — make your fix first, then re-run"

git show-ref --verify --quiet "refs/heads/${BRANCH}" \
  && die "local branch '${BRANCH}' already exists. If a prior run was interrupted, resume with:
    git switch ${BRANCH} && git push -u origin ${BRANCH} && gh pr create --base main --head ${BRANCH} --fill
  Otherwise pick another slug." || true
if git ls-remote --exit-code --heads origin "${BRANCH}" >/dev/null 2>&1; then
  die "remote branch '${BRANCH}' already exists on origin — pick another slug, or open its PR with:
    gh pr create --base main --head ${BRANCH} --fill"
fi

# Guard hook is local-only config (not carried by clone); ensure it is active.
if [ "$(git config --get core.hooksPath || true)" != ".githooks" ]; then
  note "activating local guard hook (scripts/install-hooks.sh)"
  ./scripts/install-hooks.sh
fi

# --- stage, then gate the about-to-be-committed content --------------------
# Stage everything first so the hygiene gates see NEW files exactly as CI will
# (CI checks committed content, not the unstaged working tree).
git add -A || die "git add failed"

note "running local gates (audit + js syntax + backend tests + hygiene)…"

# Reject staged Python bytecode (CI: repository-hygiene).
[ -z "$(git ls-files '*__pycache__*' '*.pyc')" ] \
  || die "tracked/staged Python bytecode present (*.pyc/__pycache__) — remove it"

# Reject whitespace errors in the staged change, incl. new files (CI: repository-hygiene).
git diff --cached --check \
  || die "whitespace errors in staged changes (see 'git diff --cached --check')"

# Syntax-check every JS/MJS bundle and audit script (CI: static-audit).
[ -d apps ] && [ -d tests ] \
  || die "expected apps/ and tests/ at the repo root — unexpected layout, aborting gate"
js_checked=0
while IFS= read -r -d '' f; do
  node --input-type=module --check < "$f" || die "JavaScript syntax error in $f"
  js_checked=$((js_checked + 1))
done < <(find apps tests -type f \( -name '*.js' -o -name '*.mjs' \) -print0)
[ "$js_checked" -gt 0 ] || die "JS syntax gate matched 0 files — unexpected, aborting"

# Structural / design audit (CI: static-audit).
node tests/embodied-platform-audit.mjs >/dev/null \
  || die "structural audit failed (run: node tests/embodied-platform-audit.mjs)"

# Python lint (CI: lint (ruff)). Fail fast locally so an agent does not push and
# then wait for CI to report a lint error.
if command -v ruff >/dev/null 2>&1; then
  ( cd backend && ruff check . ) || die "ruff lint failed (run: cd backend && ruff check .)"
elif python3 -m ruff --version >/dev/null 2>&1; then
  ( cd backend && python3 -m ruff check . ) || die "ruff lint failed (run: cd backend && python3 -m ruff check .)"
else
  die "ruff not found — install dev deps: python3 -m pip install -e 'backend[dev]'"
fi

# Backend suite against the JSON repository (CI: backend, fast subset).
# Postgres + Docker jobs are authoritative on the PR; not run locally.
( cd backend && python3 -m pytest tests -q >/dev/null ) \
  || die "backend tests failed (run: cd backend && python3 -m pytest tests -q)"

ok "all local gates passed (${js_checked} JS files checked)"

# --- branch, commit, push, PR ----------------------------------------------
# If the commit fails, return to main carrying the still-staged changes and drop
# the freshly-cut branch (safe -d: it has no commits beyond main yet).
rollback() {
  git switch "$CURRENT" >/dev/null 2>&1 || true
  git branch -d "${BRANCH}" >/dev/null 2>&1 || true
}

note "creating ${BRANCH} from ${CURRENT}…"
git switch -c "${BRANCH}" || die "could not create branch ${BRANCH}"
git commit -m "${MESSAGE}" || { rollback; die "commit failed"; }

note "pushing ${BRANCH} to origin…"
git push -u origin "${BRANCH}" \
  || die "push failed — ${BRANCH} is committed locally; resolve and run: git push -u origin ${BRANCH}"

note "opening pull request into main…"
if PR_OUT="$(gh pr create --base main --head "${BRANCH}" --title "${MESSAGE}" --fill 2>&1)"; then
  PR_URL="$PR_OUT"
else
  # A PR may already exist for this branch — try to recover its URL.
  PR_URL="$(gh pr view "${BRANCH}" --json url --jq .url 2>/dev/null || true)"
  if [ -z "$PR_URL" ]; then
    printf '%s\n' "$PR_OUT" >&2
    die "could not open a PR (gh output above). ${BRANCH} is pushed; retry with:
    gh pr create --base main --head ${BRANCH} --fill"
  fi
fi

ok "pushed ${BRANCH} and opened PR: ${PR_URL}"
note "merge happens after review + green CI; you are now on ${BRANCH}."
