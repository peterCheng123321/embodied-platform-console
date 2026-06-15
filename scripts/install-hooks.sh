#!/usr/bin/env bash
#
# install-hooks.sh — point this clone at the repo's tracked git hooks.
#
# Run once after cloning. core.hooksPath is local config and is not copied by
# `git clone`, so every contributor (and CI checkout, if desired) runs this to
# activate the pre-push guard that blocks direct pushes to main.
#
# The guard is convenience only — the authoritative lock is the server-side
# GitHub ruleset (.github/rulesets/main-protection.json). This installer refuses
# to claim success unless the hook is present, executable, AND actually rejects a
# simulated push to main: a non-executable hook is silently ignored by git, so a
# false "guard active" message would be worse than none.
#
set -euo pipefail

die() { printf '\033[31minstall-hooks: %s\033[0m\n' "$*" >&2; exit 1; }

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

HOOK=".githooks/pre-push"
[ -f "$HOOK" ] || die "missing $HOOK — wrong directory or incomplete checkout?"

git config core.hooksPath .githooks

# Make the hooks executable. Unlike a best-effort chmod, a failure here is fatal:
# git silently ignores a non-executable hook, so an inert guard must fail loud.
chmod +x "$HOOK" scripts/*.sh || die "could not set the executable bit on $HOOK"
[ -x "$HOOK" ] || die "$HOOK is not executable after chmod (read-only filesystem?)"

# Self-test: a simulated push to main MUST be rejected (exit 1). If it is not,
# the guard is not actually protecting anything — refuse to report success.
if printf 'refs/heads/main x refs/heads/main y\n' | "$HOOK" origin localtest >/dev/null 2>&1; then
  die "self-test FAILED: $HOOK did not block a simulated push to main"
fi
# And a push to a feature branch MUST be allowed (exit 0).
if ! printf 'refs/heads/fix/x x refs/heads/fix/x y\n' | "$HOOK" origin localtest >/dev/null 2>&1; then
  die "self-test FAILED: $HOOK wrongly blocked a push to a feature branch"
fi

printf '\033[32minstall-hooks:\033[0m core.hooksPath -> .githooks; pre-push guard verified (blocks main, allows fix branches)\n'
