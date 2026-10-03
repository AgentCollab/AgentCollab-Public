# AgentCollab Public Entry

AgentCollab helps teams organize AI-assisted work from request and planning through implementation, review, validation, and approval. This repository is the public starting point for the official private AgentCollab installer; it is not a setup engine.

## Quick Start

```sh
git clone https://github.com/lkhkhk/AgentCollab-Public.git
cd AgentCollab-Public
./install.sh
```

The launcher downloads the versioned installer, validates its manifest and SHA-256, and starts it only after verification. The installer then guides GitHub authentication, prerequisites, source acquisition, configuration, and canonical setup as needed. You do not need a private AgentCollab checkout to start.

## Provenance

`installer-manifest.json` is the authoritative distribution metadata for the published installer. Its `private_source.repository`, `private_source.commit`, and `private_source.path` identify the exact private source revision used to produce the public installer artifact; `install.sh` pins the same version/source identity and refuses a mismatch.

That source commit is **artifact provenance**, not an assertion that it is the current private AgentCollab Production `main`. Production deployment and installer-artifact publication have separate release evidence. To determine the exact relationship for a published version, read the versioned manifest rather than assuming the latest private branch or `main`.

See [INSTALL.md](INSTALL.md) for starting requirements and result states.