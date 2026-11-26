# Pilot

Pilot is the project manager: it owns multi-step work front to end across the KubeCoder fleet, and
the operator decides and does only what their hands must. This repository is the app. Its specs
and slices are in `pvginkel/PilotAppSpecs`, its deploy chart in `pvginkel/PilotDeploy`, and the
store environment's repository in `pvginkel/PilotProjects`.

**Status**: version 1 is in production; development continues.

One append-only timeline per managed project shows its work, its decision documents and their asks,
and a side chat talks to Pilot's brain, a headless Claude Code session in the store environment.
The app is a Flask backend with Pilot's MCP server beside it, a React + Vite frontend,
`pilot-sync`, the store environment's sync sidecar, and the collector, which reads the fleet's
Claude Code transcripts. It is built on the ModernAppTemplate stack (Flask on PostgreSQL,
React + Vite, Playwright), which CI builds and Argo CD deploys: every green build to the dev stage
at `https://pilot-dev.home`, and production at `https://pilot.ginbov.nl` when the operator promotes
it ([`docs/deployment.md`](docs/deployment.md)). The topic docs under [`docs/`](docs/) describe each
part as built.
