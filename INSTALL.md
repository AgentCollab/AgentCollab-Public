# Installation start

## Starting requirements

- Linux for the current private development installer flow.
- POSIX-compatible shell, `curl`, Python 3, and either `sha256sum` or `shasum`.
- An internet connection to retrieve the public manifest and installer artifact over HTTPS.

The private installer checks later host tools and GitHub authority itself and explains any required operator action. No private checkout or private GitHub access is needed to download the public installer artifact.

## Start

From a clone of [AgentCollab-Public](https://github.com/lkhkhk/AgentCollab-Public), run:

```sh
./install.sh
```

The launcher verifies the pinned release manifest and artifact SHA-256 before it executes the installer. It removes its temporary download directory on exit.

## Installer states

- `ACTION_REQUIRED`: an operator action or prerequisite is needed; follow the printed next step and rerun safely.
- `BLOCKED`: a safety or integrity gate stopped the flow; resolve the stated cause before retrying.
- `READY`: canonical setup and verification completed and the installer printed the next handoff.

This page covers only how to start the installer. The private installer and canonical setup/doctor authorities own all later installation decisions.
