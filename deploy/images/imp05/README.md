# IMP-05 qualification image

Build from the repository root after `pnpm build`:

```
docker build -f deploy/images/imp05/Dockerfile -t care-link-imp05:source .
```

The image uses existing immutable Python/uv inputs and the locked workspace. It contains role modules, public synthetic configuration, migrations and the built web client. This is a qualification artifact; separate runtime credentials, protected sockets, admitted signed simulator mapping and receiver service assignments are supplied externally. Its default command prints help. Building or running that help command does not deploy a target. See tools/imp05_runtime/README.md for explicit process binding.
