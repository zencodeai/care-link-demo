# Browser contract adapters

The runtime imports `validators.generated.cjs`, ordinary Ajv standalone functions produced offline from the unchanged reviewed schema snapshot. It never constructs Ajv, compiles a schema, or evaluates a function string in a browser. The existing strict CSP therefore needs no `unsafe-eval` exception.

From the repository root, after pinned locked dependency setup:

```sh
python3 tools/generate_contracts.py
python3 tools/generate_contracts.py --check
```

The Python tool preserves its source/DTO snapshot checks and invokes `tools/generate_browser_validators.mjs`. The Node tool uses the package's pinned Ajv/ajv-formats versions, emits deterministic CommonJS plus a typed declaration, and supports `--check` without acquiring dependencies. Its public contract-name set remains the same 24 selected contracts. Generated files record the schema byte hash and compiler versions; edit the source/generator and regenerate rather than modifying compiled output.

`x-decimalMaximum` uses Ajv CodeGen to preserve canonical ASCII decimal strings and exact BigInt bounds. Runtime JSON parsing still rejects duplicate/escaped-duplicate keys, unknown shapes, inappropriate coercion, nonfinite values and invalid Unicode. No schema or DTO definition was loosened. The generated functions retain only plain format/Unicode-length runtime helpers; no schema compiler runs at application startup.

Vite explicitly handles the generated CommonJS module for production and prebundles the linked workspace package during development. Restart the development server with `--force` after regenerating a linked package. Tests execute the compiled functions with string-code generation disabled and retain Python/TypeScript differential fixtures. Production bundle startup is also checked under the unchanged strict CSP before actual lab qualification; a mocked startup fixture does not establish authenticated actor behavior.
