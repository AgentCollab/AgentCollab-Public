# AgentCollab Public Entry

AgentCollab helps teams organize AI-assisted work from request and planning through implementation, review, validation, and approval. This repository is the public starting point for the official private AgentCollab installer; it is not a setup engine.

## Quick Start

```sh
git clone https://github.com/lkhkhk/AgentCollab-Public.git
cd AgentCollab-Public
./install.sh
```

The launcher downloads the versioned installer, validates its manifest and SHA-256, and starts it only after verification. The installer then guides GitHub authentication, prerequisites, source acquisition, configuration, and canonical setup as needed. You do not need a private AgentCollab checkout to start.

See [INSTALL.md](INSTALL.md) for starting requirements and result states.
