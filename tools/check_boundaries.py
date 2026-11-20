"""Check declared Python and TypeScript source dependency directions without importing code."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "contracts": {"contracts"},
    "domain": {"domain"},
    "policy_input": {"policy_input", "contracts", "domain"},
    "recovery_control": {"recovery_control", "contracts", "domain"},
    "core": {"core", "contracts", "domain", "policy_input", "rendering"},
    "runtime": {"runtime", "contracts"},
    "simulators": {"simulators", "contracts", "domain"},
    "data": {"data", "contracts", "domain", "policy_input"},
    "web": {"contracts"},
    "identity": {"identity", "contracts", "domain"},
    "help": {"help", "contracts"},
    "static": {"static", "contracts"},
}


def violations(owner: str, imports: list[str]) -> list[str]:
    failures: list[str] = []
    for name in imports:
        normalized = name.replace("@care-link/", "care_link_").replace("-", "_")
        segments = normalized.replace("/", ".").split(".")
        target = next(
            (part.removeprefix("care_link_") for part in segments if part.startswith("care_link_")),
            next((part for part in segments if part in ALLOWED), None),
        )
        if (
            target
            and target != owner
            and (
                target not in ALLOWED.get(owner, {owner, "contracts"})
                or any(
                    part.startswith("care_link_") and i < len(segments) - 1
                    for i, part in enumerate(segments)
                )
            )
        ):
            failures.append(f"{owner} cannot import {name}")
        if owner in {"runtime", "core", "domain", "contracts", "web"} and segments[0] in {
            "sqlalchemy",
            "psycopg",
            "psycopg2",
            "sqlite3",
        }:
            failures.append(f"{owner} cannot import persistence driver {name}")
        if owner == "domain" and segments[0] in {"fastapi", "httpx", "uvicorn"}:
            failures.append(f"domain cannot import framework/transport {name}")
    return failures


def check(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    for base in ("services", "packages", "apps", "host"):
        for path in (root / base).rglob("*"):
            if set(path.parts) & {"node_modules", "dist", "tests", "__pycache__"}:
                continue
            relative = path.relative_to(root)
            if path.suffix == ".py":
                owner = relative.parts[1].replace("-", "_")
                tree = ast.parse(path.read_text(), filename=str(relative))
                imports = [
                    alias.name
                    for n in ast.walk(tree)
                    if isinstance(n, ast.Import)
                    for alias in n.names
                ]
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ImportFrom):
                        continue
                    if node.level:
                        target_path = path.parent
                        for _ in range(node.level - 1):
                            target_path = target_path.parent
                        target_path = target_path.joinpath(*(node.module or "").split("."))
                        package_root = path
                        while package_root.parent != root and package_root.name != "src":
                            package_root = package_root.parent
                        if package_root.name != "src" or not target_path.is_relative_to(
                            package_root
                        ):
                            failures.append(f"{relative}: relative import leaves source package")
                    else:
                        imports.append(node.module or "")
                for n in ast.walk(tree):
                    if isinstance(n, ast.Call) and (
                        isinstance(n.func, ast.Name)
                        and n.func.id == "__import__"
                        or isinstance(n.func, ast.Attribute)
                        and n.func.attr == "import_module"
                    ):
                        failures.append(
                            f"{relative}: dynamic imports require explicit boundary review"
                        )
            elif path.suffix in {".ts", ".tsx"} and not path.name.endswith(
                (".test.ts", ".test.tsx")
            ):
                owner = "web" if base == "apps" else relative.parts[1]
                imports = re.findall(
                    r'(?:from\s*|import\s*\(|import\s*)[\'"]([^\'"]+)', path.read_text()
                )
                for name in imports:
                    if name.startswith("."):
                        resolved = (path.parent / name).resolve()
                        allowed = (
                            root / "apps/web" if owner == "web" else root / "packages/contracts"
                        ).resolve()
                        if not resolved.is_relative_to(allowed):
                            failures.append(f"{relative}: relative cross-package import {name}")
            else:
                continue
            failures.extend(f"{relative}: {v}" for v in violations(owner, imports))
    return failures


if __name__ == "__main__":
    found = check()
    if found:
        raise SystemExit("\n".join(found))
    print("Source dependency boundaries passed (source check, not runtime isolation).")
