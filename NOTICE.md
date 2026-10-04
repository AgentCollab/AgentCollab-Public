# Public installer boundary

This repository contains the generic installer entry point, bootstrap, protocol metadata, documentation, and tests. It does not contain product-version selection, Runtime/Execution package bytes, or private release manifests.

The private `AgentCollab/AgentCollab-Distribution` repository is the immutable product-version authority. Public users authenticate with GitHub CLI; the bootstrap reads channel/version catalog entries with authenticated `gh api` and downloads only the exact versioned release assets selected by the catalog or explicit `--version`.
