# IMP-06 source qualification image

Build after `pnpm build` with `docker build -f deploy/images/imp06/Dockerfile -t care-link-imp06:source .`. The immutable Python/uv inputs and locked source workspace are retained. This is a broad qualification artifact, not a credential or process isolation boundary; source factories in tools/imp06_runtime construct roles with separate credentials, authenticated ports and a verified release. The default command prints a source-artifact notice. It opens no listener and admits no model.
