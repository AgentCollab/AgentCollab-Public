# Install AgentCollab

1. Clone this Public repository and run `./install.sh` from its root. The launcher verifies that its files match the same checked-out Public commit.
2. Install GitHub CLI and authenticate with `gh auth login`.
3. Confirm the selected identity can read private `AgentCollab/AgentCollab-Distribution`.
4. Review a plan before applying it:

   ```sh
   ./install.sh plan
   ./install.sh plan --channel beta
   ./install.sh plan --version VERSION
   ```

   No selector uses `channels/default.json`. A channel selector uses that channel's pointer. `--version` reads the exact immutable version record and bypasses channel pointers. Combining `--version` and `--channel` is blocked.

5. Apply only the reviewed plan, passing its `plan_sha256`:

   ```sh
   ./install.sh apply --approved-plan-sha256 PLAN_SHA256 --version VERSION
   ```

   Use the exact `resolved_version` shown during PLAN. This prevents a changed channel pointer from silently selecting a different candidate.

6. Verify with the same exact version:

   ```sh
   ./install.sh verify --version VERSION
   ```

If `--web-port` is omitted, it remains omitted when the bootstrap calls setup so setup can choose its implicit default/fallback. If explicitly supplied, the exact value is forwarded. The default installation root is `./agentcollab` relative to the current working directory; `--installation-root <path>` overrides it.

Catalog reads use authenticated `gh api` calls. Distribution package downloads use the exact release tag in the resolved version record. Pointer, version-record, release-manifest, package, and source provenance checks fail closed; the installer does not fall back to another version.
