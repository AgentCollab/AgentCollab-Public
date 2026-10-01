#!/bin/sh
set -eu

VERSION='0.1.0'
PRIVATE_SOURCE_SHA='3980ee450f373f36cc516ae0b9c49790083973c0'
MANIFEST_URL="https://raw.githubusercontent.com/lkhkhk/AgentCollab-Public/v${VERSION}/installer-manifest.json"
EXPECTED_ARTIFACT_URL="https://github.com/lkhkhk/AgentCollab-Public/releases/download/v${VERSION}/agentcollab-installer.py"
ARTIFACT_NAME='agentcollab-installer.py'

fail() {
    printf '%s\n' "AgentCollab installer launcher: $1" >&2
    exit 1
}

command -v curl >/dev/null 2>&1 || fail 'curl is required to retrieve the verified public installer.'
command -v python3 >/dev/null 2>&1 || fail 'Python 3 is required to validate the manifest and run the installer.'
if command -v sha256sum >/dev/null 2>&1; then
    DIGEST_TOOL='sha256sum'
elif command -v shasum >/dev/null 2>&1; then
    DIGEST_TOOL='shasum'
else
    fail 'sha256sum or shasum is required to verify the installer.'
fi

TMP_ROOT=${TMPDIR:-/tmp}
DOWNLOAD_DIR=$(mktemp -d "${TMP_ROOT%/}/agentcollab-installer.XXXXXXXX") || fail 'could not create a private temporary directory.'
cleanup() {
    rm -rf "$DOWNLOAD_DIR"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

MANIFEST_FILE="$DOWNLOAD_DIR/installer-manifest.json"
ARTIFACT_FILE="$DOWNLOAD_DIR/$ARTIFACT_NAME"
curl -fsSL --proto '=https' --tlsv1.2 --output "$MANIFEST_FILE" "$MANIFEST_URL" || fail 'could not download the official installer manifest over HTTPS.'

EXPECTED_SHA=$(python3 - "$MANIFEST_FILE" "$VERSION" "$PRIVATE_SOURCE_SHA" "$ARTIFACT_NAME" "$EXPECTED_ARTIFACT_URL" <<'PY'
import json
import re
import sys
from pathlib import Path

path, version, source_sha, artifact_name, artifact_url = sys.argv[1:]
try:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError
    private_source = manifest["private_source"]
    artifact = manifest["artifact"]
except (OSError, KeyError, TypeError, json.JSONDecodeError):
    raise SystemExit("manifest is missing or invalid")
if not isinstance(private_source, dict) or not isinstance(artifact, dict):
    raise SystemExit("manifest source or artifact entry is invalid")
if manifest.get("schema_version") != 1 or manifest.get("channel") != "stable":
    raise SystemExit("unsupported installer manifest schema or channel")
if manifest.get("version") != version:
    raise SystemExit("installer version does not match the launcher")
if manifest.get("public_repository") != "lkhkhk/AgentCollab-Public":
    raise SystemExit("public repository identity does not match the launcher")
if private_source.get("repository") != "lkhkhk/AgentCollab" or private_source.get("commit") != source_sha:
    raise SystemExit("private source provenance does not match the reviewed candidate")
if private_source.get("path") != "deploy/guided_installer.py":
    raise SystemExit("private source path does not match the reviewed installer entry")
if artifact.get("name") != artifact_name or artifact.get("url") != artifact_url:
    raise SystemExit("installer artifact identity or retrieval URL does not match the launcher")
digest = artifact.get("sha256")
if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
    raise SystemExit("installer SHA-256 metadata is missing or invalid")
print(digest)
PY
) || fail 'manifest validation failed; refusing to execute an installer.'

curl -fsSL --proto '=https' --tlsv1.2 --output "$ARTIFACT_FILE" "$EXPECTED_ARTIFACT_URL" || fail 'could not download the official installer artifact over HTTPS.'
if [ "$DIGEST_TOOL" = 'sha256sum' ]; then
    DIGEST_LINE=$(sha256sum "$ARTIFACT_FILE") || fail 'could not calculate installer SHA-256.'
else
    DIGEST_LINE=$(shasum -a 256 "$ARTIFACT_FILE") || fail 'could not calculate installer SHA-256.'
fi
ACTUAL_SHA=${DIGEST_LINE%% *}
[ "$ACTUAL_SHA" = "$EXPECTED_SHA" ] || fail 'installer SHA-256 mismatch; refusing to execute downloaded bytes.'

python3 "$ARTIFACT_FILE" "$@"
