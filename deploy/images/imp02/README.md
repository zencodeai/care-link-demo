# Isolated IMP-02 qualification images

Build from the repository root only after both actual main/help client bundles exist. `Dockerfile.dockerignore` limits the application image context to selected source and built public assets; no secrets or evidence. The runtime requires a selected role, protected external config and assigned kernel UID/socket custody. It has no default configured listeners, credentials or participant admission.

`Keycloak.Dockerfile` prebuilds the exact pinned provider for PostgreSQL and health support. Record each actual resulting digest before creating lab manifests. These sources do not qualify a running trust boundary.

The runtime includes only the lab trust-process entrypoint from the orchestration package. Cluster rendering/acquisition/probe utilities run from coordinator source and are excluded from runtime images. The verification target adds locked test dependencies and native fixture source; it is not the application runtime.
