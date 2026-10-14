# Pilot

Pilot is the project manager: it owns multi-step work front to end across the KubeCoder fleet, and
the operator decides and does only what their hands must. This repository is the app. Its specs
and slices are in `pvginkel/PilotAppSpecs`, its deploy chart in `pvginkel/PilotDeploy`, and the
store environment's repository in `pvginkel/PilotProjects`.

**Status**: no feature built yet. The repository holds the ModernAppTemplate skeleton (Flask on
PostgreSQL, React + Vite, Playwright), which CI builds and Argo CD deploys to production at
`https://pilot.ginbov.nl` ([`docs/deployment.md`](docs/deployment.md)), and version 1 is being
planned.
