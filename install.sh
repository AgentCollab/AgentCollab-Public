#!/bin/sh
set -eu

VERSION='candidate-691-1a5def1-r2'
PUBLIC_REPOSITORY='lkhkhk/AgentCollab-Public'
MANIFEST_URL="https://raw.githubusercontent.com/${PUBLIC_REPOSITORY}/${VERSION}/installer-manifest.json"
BOOTSTRAP_URL="https://github.com/${PUBLIC_REPOSITORY}/releases/download/${VERSION}/agentcollab-bootstrap.py"

fail() { printf '%s\n' "AgentCollab installer: $1" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || fail 'curl is required.'
command -v python3 >/dev/null 2>&1 || fail 'Python 3 is required.'
if command -v sha256sum >/dev/null 2>&1; then DIGEST_TOOL=sha256sum
elif command -v shasum >/dev/null 2>&1; then DIGEST_TOOL=shasum
else fail 'sha256sum or shasum is required.'; fi

TMP_ROOT=${TMPDIR:-/tmp}
DOWNLOAD_DIR=$(mktemp -d "${TMP_ROOT%/}/agentcollab-bootstrap.XXXXXXXX") || fail 'could not create a private temporary directory.'
cleanup() { rm -rf "$DOWNLOAD_DIR"; }
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

MANIFEST_FILE="$DOWNLOAD_DIR/installer-manifest.json"
BOOTSTRAP_FILE="$DOWNLOAD_DIR/agentcollab-bootstrap.py"
curl -fsSL --proto '=https' --tlsv1.2 --output "$MANIFEST_FILE" "$MANIFEST_URL" || fail 'could not retrieve the candidate manifest.'
EXPECTED_SHA=$(python3 - "$MANIFEST_FILE" "$VERSION" "$PUBLIC_REPOSITORY" <<'PY'
import json, re, sys
from pathlib import Path
path, version, repository = sys.argv[1:]
try:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    artifact = value['bootstrap']
except (OSError, KeyError, TypeError, json.JSONDecodeError):
    raise SystemExit('candidate manifest is invalid')
if (not isinstance(value, dict) or value.get('schema_version') != 1
        or value.get('channel') != 'candidate' or value.get('version') != version
        or value.get('public_repository') != repository
        or not isinstance(artifact, dict) or artifact.get('name') != 'agentcollab-bootstrap.py'):
    raise SystemExit('candidate identity is invalid')
digest = artifact.get('sha256')
if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
    raise SystemExit('bootstrap SHA-256 is invalid')
print(digest)
PY
) || fail 'candidate manifest validation failed.'

curl -fsSL --proto '=https' --tlsv1.2 --output "$BOOTSTRAP_FILE" "$BOOTSTRAP_URL" || fail 'could not retrieve the candidate bootstrap.'
if [ "$DIGEST_TOOL" = sha256sum ]; then DIGEST_LINE=$(sha256sum "$BOOTSTRAP_FILE")
else DIGEST_LINE=$(shasum -a 256 "$BOOTSTRAP_FILE"); fi
ACTUAL_SHA=${DIGEST_LINE%% *}
[ "$ACTUAL_SHA" = "$EXPECTED_SHA" ] || fail 'bootstrap SHA-256 mismatch.'
python3 "$BOOTSTRAP_FILE" --manifest "$MANIFEST_FILE" "$@"
