#!/bin/bash
# Review branches only: this gate cannot deploy the factory main branch.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "${1:-}" = '--branch' ] || { echo 'Use --branch review-branch'; exit 1; }
branch=${2:?Review branch required}
[ "$branch" != main ] && [ "$branch" != master ] || { echo 'Production push forbidden'; exit 1; }
git check-ref-format --branch "$branch" >/dev/null
[ "$(git branch --show-current)" = "$branch" ]
git diff --quiet && git diff --cached --quiet
bash tools/check.sh
git push -u origin "$branch"
