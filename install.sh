#!/bin/sh
set -eu

PUBLIC_REPOSITORY='AgentCollab/AgentCollab-Public'

fail() { printf '%s\n' "AgentCollab installer: $1" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || fail 'Python 3 is required.'
command -v git >/dev/null 2>&1 || fail 'Git is required; run install.sh from a Public repository checkout.'

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || fail 'could not resolve installer directory.'
REPOSITORY_ROOT=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null) || \
  fail 'run install.sh from a checked-out AgentCollab Public repository.'
[ "$SCRIPT_DIR" = "$REPOSITORY_ROOT" ] || fail 'run install.sh from the Public repository root.'

# Keep launcher, generic metadata, and bootstrap tied to the same checked-out commit.
for FILE in install.sh installer-manifest.json agentcollab-bootstrap.py; do
  EXPECTED_BLOB=$(git -C "$REPOSITORY_ROOT" rev-parse "HEAD:$FILE" 2>/dev/null) || \
    fail "current Public commit is missing $FILE."
  ACTUAL_BLOB=$(git -C "$REPOSITORY_ROOT" hash-object "$REPOSITORY_ROOT/$FILE" 2>/dev/null) || \
    fail "could not verify $FILE against the current Public commit."
  [ "$EXPECTED_BLOB" = "$ACTUAL_BLOB" ] || \
    fail 'installer files differ from the same committed Public revision; use a clean checkout.'
done

BOOTSTRAP_FILE="$REPOSITORY_ROOT/agentcollab-bootstrap.py"
MANIFEST_FILE="$REPOSITORY_ROOT/installer-manifest.json"
[ -f "$BOOTSTRAP_FILE" ] && [ -f "$MANIFEST_FILE" ] || fail 'generic Public installer files are incomplete.'
exec python3 "$BOOTSTRAP_FILE" --manifest "$MANIFEST_FILE" "$@"
