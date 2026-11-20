"""Audit the fixed IMP04 allowlist's ordered sensitive-path exclusions."""

from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "deploy/images/imp04/Dockerfile.dockerignore"


def rules():
    return [
        line.strip()
        for line in RULES.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def admitted(path):
    # These fixtures exercise the file's existing literal/*/** pattern subset;
    # parent-directory exclusions also prevent traversal into private caches.
    patterns = rules()

    def selected(candidate):
        included = True
        for pattern in patterns:
            negated = pattern.startswith("!")
            expression = pattern.removeprefix("!").rstrip("/")
            if fnmatchcase(candidate, expression):
                included = negated
        return included

    return all(
        selected(str(part))
        for part in [PurePosixPath(path), *PurePosixPath(path).parents]
        if str(part) != "."
    )


@pytest.mark.parametrize(
    "path",
    [
        "config/demo/imp04/private.key",
        "config/demo/imp04/nested/private.pem",
        "config/demo/imp04/.env",
        "config/demo/imp04/nested/.env.production",
        "config/demo/imp04/__pycache__/config.pyc",
        "config/demo/imp04/.pytest_cache/state.json",
        "config/demo/imp04/node_modules/package/index.js",
        "config/demo/imp04/tests/fixture.json",
        "config/demo/imp04/public.js.map",
    ],
)
def test_private_config_and_generated_files_are_not_admitted(path):
    assert not admitted(path)


@pytest.mark.parametrize(
    "path",
    [
        "config/demo/imp04/directory-source.json",
        "config/demo/imp04/nested/public.json",
        "tools/imp04_review/operator.py",
    ],
)
def test_public_configuration_and_review_modules_remain_admitted(path):
    assert admitted(path)


def test_sensitive_deny_rules_follow_every_allowlist_exception():
    patterns = rules()
    last_allow = max(index for index, pattern in enumerate(patterns) if pattern.startswith("!"))
    for sensitive in (
        "**/__pycache__",
        "**/.pytest_cache",
        "**/node_modules",
        "**/.env*",
        "**/*.key",
        "**/*.pem",
        "**/*.map",
        "**/tests",
        "**/tests/**",
    ):
        assert patterns.index(sensitive) > last_allow
