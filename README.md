# AgentCollab Public Installer

This repository provides the generic AgentCollab installer protocol. It does not select or contain a current product release. The private `AgentCollab/AgentCollab-Distribution` repository is the authenticated authority for immutable version records, release manifests, and Runtime/Execution packages.

## Use

Clone the Public repository and run its installer from the checkout:

```sh
git clone https://github.com/AgentCollab/AgentCollab-Public.git
cd AgentCollab-Public
gh auth login
./install.sh plan
```

The GitHub identity must have read access to the private Distribution repository. The default installation root is `./agentcollab` under the current working directory.

```sh
./install.sh plan                       # Distribution default pointer
./install.sh plan --channel beta        # beta pointer
./install.sh plan --channel stable      # stable pointer
./install.sh plan --version VERSION     # exact immutable version
```

`--version` and `--channel` cannot be combined. Exact versions bypass channel pointers. A resolved version is used for all subsequent manifest/package reads; there is no fallback to another version.

The bootstrap reports the requested selector, resolved version, Distribution release identity, and exact Source SHA to standard error. It verifies the channel pointer's version-record digest, release-manifest digest, Runtime/Execution hashes and provenance before invoking the setup engine.

The setup engine chooses a Web port automatically when `--web-port` is omitted. An explicit `--web-port N` is forwarded unchanged.
