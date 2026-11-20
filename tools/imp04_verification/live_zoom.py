"""Native bilingual keyboard, axe and Chrome Settings zoom qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import cast
from uuid import UUID

from tools.imp04_deployment.config import MAIN, PRIVATE, REPO, load, record, write
from tools.imp04_deployment.docker import PREFIX, inspect_container
from tools.imp04_verification.browser_route import address_pin as address_pin

ACTORS = {
    "pid": "pid",
    "carer": "carer",
    "professional": "professional_participant",
    "worker1": "worker",
}
LOCALES = ("en-CA", "fr-CA")
VERSION = "imp04.native-accessibility.v1"
AXE_VERSION = "4.14.0"
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21aa"]

# No remote modules from this repository are needed; cookies arrive solely on stdin.
SCRIPT = Path(__file__).with_name("native_browser.cjs").read_text()
AXE_LOADER = r"""
const fs = require('node:fs'), path = require('node:path');
const {createRequire} = require('node:module');
const entry = require.resolve('@axe-core/playwright');
const axeRequire = createRequire(entry);
const pkg = axeRequire('axe-core/package.json');
const file = fs.realpathSync(axeRequire.resolve('axe-core/axe.min.js'));
if (pkg.name !== 'axe-core' || pkg.version !== '4.14.0' ||
    !file.startsWith(fs.realpathSync('node_modules') + path.sep))
  throw Error('Pinned axe required');
console.log(JSON.stringify({source:fs.readFileSync(file,'utf8'),version:pkg.version}));
"""


def axe_bundle() -> dict[str, str]:
    """Resolve the installed, locked scanner without installing or executing its source."""
    try:
        result = subprocess.run(  # noqa: S603 - fixed local dependency reader
            [shutil.which("node") or "node", "-e", AXE_LOADER],
            cwd=REPO,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        value = record(json.loads(result.stdout))
        source = value.get("source")
        if result.returncode or value.get("version") != AXE_VERSION or not isinstance(source, str):
            raise ValueError("Pinned scanner required")
        if len(source) < 100_000:
            raise ValueError("Complete installed scanner required")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise RuntimeError("Pinned local axe source unavailable; diagnostics suppressed") from None
    return {
        "axe_source": source,
        "axe_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "axe_version": AXE_VERSION,
    }


def _directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise ValueError("Owner-only real directory required")


def payload(state: Path) -> dict[str, object]:
    """Read only the fixed actor bindings and genuine main-origin cookie material."""
    if not state.is_absolute() or state.parent != PRIVATE or state.name in {".", ".."}:
        raise ValueError("Exact private prior evidence directory required")
    for path in (PRIVATE, state, state / "sessions"):
        _directory(path)
    config = load(PRIVATE / "browser.json")
    if config.get("mainOrigin") != MAIN or config.get("ignoreHTTPSErrors") is True:
        raise ValueError("Exact native TLS origin required")
    configured = record(config["actors"])
    actors: list[dict[str, object]] = []
    for slot, role in ACTORS.items():
        actor = record(configured[slot])
        account = actor.get("accountId")
        if (
            not isinstance(account, str)
            or str(UUID(account)) != account
            or actor.get("role") != role
        ):
            raise ValueError("Exact canonical issued account and role required")
        saved = load(state / "sessions" / (slot + ".json"))
        values = saved.get("cookies")
        if not isinstance(values, list):
            raise ValueError("Genuine browser cookie collection required")
        cookies: list[dict[str, object]] = []
        for value in cast(list[object], values):
            cookie = record(value)
            if cookie.get("domain") != "plans.localhost":
                continue
            if (
                cookie.get("name") not in {"__Host-care-link-session", "__Host-care-link-binding"}
                or cookie.get("path") != "/"
                or cookie.get("secure") is not True
                or cookie.get("httpOnly") is not True
                or not isinstance(cookie.get("value"), str)
                or not cookie["value"]
            ):
                raise ValueError("Unmodified secure main-origin session cookies required")
            cookies.append(cookie)
        names = [cookie["name"] for cookie in cookies]
        if "__Host-care-link-session" not in names or len(names) != len(set(names)):
            raise ValueError("One genuine main-origin session cookie required")
        actors.append({"slot": slot, "account_id": account, "role": role, "cookies": cookies})
    if len({actor["account_id"] for actor in actors}) != len(ACTORS):
        raise ValueError("Separate issued actor accounts required")
    return {"version": VERSION, "origin": MAIN, "locales": LOCALES, "actors": actors}


def run(state: Path, output: Path) -> dict[str, object]:
    source = payload(state)
    if output.is_symlink() or output.exists() or not output.is_absolute():
        raise ValueError("New absolute evidence output required")
    _directory(output.parent)
    source.update(axe_bundle())
    source["axe_tags"] = AXE_TAGS
    executable = shutil.which("docker")
    browser = inspect_container(PREFIX + "-review-chrome")
    identifier = browser.get("Id")
    if (
        executable is None
        or not isinstance(identifier, str)
        or not re.fullmatch("[0-9a-f]{64}", identifier)
    ):
        raise ValueError("Owned immutable browser container required")
    source["address_pin"] = address_pin(browser, inspect_container(PREFIX + "-ingress"))
    try:
        result = subprocess.run(  # noqa: S603 - fixed inspected container; private input only on stdin
            [executable, "exec", "--interactive", identifier, "node", "-e", SCRIPT],
            input=json.dumps(source),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=240,
            check=False,
        )
        value = record(json.loads(result.stdout))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise RuntimeError("Native zoom runner failed; private diagnostics suppressed") from None
    if (
        result.returncode
        or value.get("version") != VERSION
        or set(value) != {"version", "observations"}
    ):
        raise RuntimeError("Native zoom runner failed; private diagnostics suppressed")
    rows = value.get("observations")
    if not isinstance(rows, list) or len(cast(list[object], rows)) != 8:
        raise RuntimeError("Eight native zoom observations required")
    rows = cast(list[object], rows)
    actors = cast(list[dict[str, object]], source["actors"])
    for item, (actor, locale) in zip(
        rows, ((a, loc) for a in actors for loc in LOCALES), strict=True
    ):
        row = record(item)
        if any(
            row.get(key) != expected
            for key, expected in {
                "slot": actor["slot"],
                "account_id": actor["account_id"],
                "role": actor["role"],
                "locale": locale,
            }.items()
        ) or row.get("status") not in {"passed", "failed"}:
            raise RuntimeError("Exact actor and locale observation binding required")
        validate_observation(row)
        if (
            "accessibility" in row
            and record(row["accessibility"])["source_sha256"] != source["axe_sha256"]
        ):
            raise RuntimeError("Observed scanner source differs from the installed pinned scanner")
    value["status"] = "passed" if all(record(r)["status"] == "passed" for r in rows) else "failed"
    value["review_scope"] = (
        "Automated native keyboard, full-page axe and zoom checks; human review remains separate"
    )
    value["axe"] = {"version": AXE_VERSION, "source_sha256": source["axe_sha256"], "tags": AXE_TAGS}
    value["watchdog"] = {
        "remote_seconds": 210,
        "host_timeout_seconds": 240,
        "context_close": "best_effort",
    }
    value["not_run"] = ["human_visual_review", "manual_screen_reader"]
    write(output, json.dumps(value, indent=2) + "\n")
    return value


def validate_observation(row: dict[str, object]) -> None:
    """Keep the public evidence contract fixed, including strict measured zoom ratios."""
    allowed = {
        "slot",
        "account_id",
        "role",
        "locale",
        "status",
        "stage",
        "baseline",
        "enlarged",
        "keyboard_tabs",
        "control_reachable",
        "session_status",
        "scroll_end",
        "scroll_limit",
        "profile_removed",
        "accessibility",
        "zoom_restored",
        "current_access_completed_200",
        "substage",
        "error_category",
        "initial_session_status",
        "directory_status",
        "cleanup",
        "deadline_elapsed",
    }
    stages = {
        "launch",
        "settings",
        "navigation",
        "baseline",
        "identity",
        "native_zoom",
        "keyboard",
        "scroll",
        "complete",
        "restore_zoom",
        "cleanup",
        "deadline",
        "access_check",
        "directory_search",
        "invalid_plan",
        "input_focus",
        "axe_scan",
        "unload",
    }
    if set(row) - allowed or row.get("stage") not in stages:
        raise RuntimeError("Fixed safe native zoom observation required")
    substages = {
        "start",
        "navigate",
        "http_status",
        "activate",
        "wait_ready",
        "enabled",
        "localized_labels",
        "focus_input",
        "tab",
        "focus_assert",
        "scan",
        "zoom",
        "walk_tabs",
        "visible_bounds",
        "scroll",
        "restore",
        "close",
    }
    if "substage" in row and row["substage"] not in substages:
        raise RuntimeError("Fixed safe browser failure substage required")
    if "error_category" in row and (
        row["error_category"] not in {"driver_timeout", "check_failed", "driver_error"}
        or "substage" not in row
        or row["status"] == "passed"
    ):
        raise RuntimeError("Fixed safe browser error category required")
    if "deadline_elapsed" in row and (
        type(row["deadline_elapsed"]) is not bool or row["status"] == "passed"
    ):
        raise RuntimeError("Actual failed deadline metadata required")
    cleanup = record(row.get("cleanup"))
    if (
        set(cleanup)
        != {
            "status",
            "zoom_restored",
            "page_unloaded",
            "context_closed",
            "profile_removed",
            "failures",
        }
        or cleanup["status"] not in {"passed", "failed", "not_run"}
        or any(
            type(cleanup[key]) is not bool
            for key in ("zoom_restored", "page_unloaded", "context_closed", "profile_removed")
        )
    ):
        raise RuntimeError("Fixed safe cleanup evidence required")
    cleanup_failures = cleanup["failures"]
    if not isinstance(cleanup_failures, list):
        raise RuntimeError("Safe cleanup failure list required")
    cleanup_failures = cast(list[object], cleanup_failures)
    for item in cleanup_failures:
        entry = record(item)
        if (
            set(entry) != {"stage", "substage", "error_category"}
            or entry["stage"] not in {"restore_zoom", "unload", "cleanup"}
            or entry["substage"] not in {"restore", "navigate", "close"}
            or entry["error_category"] not in {"driver_timeout", "check_failed", "driver_error"}
        ):
            raise RuntimeError("Fixed safe cleanup failure required")
    if (cleanup["status"] == "failed") != bool(cleanup_failures) or (
        row["status"] == "passed"
        and (
            cleanup["status"] != "passed"
            or not all(
                cleanup[key] is True
                for key in ("zoom_restored", "page_unloaded", "context_closed", "profile_removed")
            )
        )
    ):
        raise RuntimeError("Complete successful cleanup required for a passing row")
    for key in ("initial_session_status", "directory_status", "session_status"):
        if key in row and (type(row[key]) is not int or not 100 <= cast(int, row[key]) <= 599):
            raise RuntimeError("Actual safe HTTP status required")
    if "accessibility" in row:
        validate_accessibility(record(row["accessibility"]), passed=row["status"] == "passed")
    if row["status"] != "passed":
        return
    if "accessibility" not in row:
        raise RuntimeError("Complete native keyboard and axe evidence required")
    measured: list[dict[str, float]] = []
    for key in ("baseline", "enlarged"):
        metric = record(row.get(key))
        if set(metric) != {"dpr", "width", "outer", "pinch", "height"} or any(
            type(v) not in {int, float} or not math.isfinite(cast(float, v)) or cast(float, v) <= 0
            for v in metric.values()
        ):
            raise RuntimeError("Actual numeric native zoom metrics required")
        measured.append(cast(dict[str, float], metric))
    before, after = measured
    tabs, end, limit = row.get("keyboard_tabs"), row.get("scroll_end"), row.get("scroll_limit")
    if (
        row.get("stage") != "complete"
        or row.get("profile_removed") is not True
        or row.get("control_reachable") is not True
        or row.get("zoom_restored") is not True
        or row.get("current_access_completed_200") is not True
        or row.get("initial_session_status") != 200
        or row.get("directory_status") != 200
        or row.get("session_status") != 200
        or type(tabs) is not int
        or not 1 <= tabs <= 80
        or type(end) not in {int, float}
        or type(limit) not in {int, float}
        or not math.isfinite(cast(float, end))
        or not math.isfinite(cast(float, limit))
        or cast(float, end) < 0
        or cast(float, limit) < 0
        or (cast(float, limit) > 0 and cast(float, end) <= 0)
        or abs(after["dpr"] / before["dpr"] - 2) >= 0.02
        or abs(after["width"] * 2 - before["width"]) > 2
        or abs(after["outer"] - before["outer"]) > 1
        or abs(after["pinch"] - before["pinch"]) >= 0.01
    ):
        raise RuntimeError("Native zoom or keyboard qualification did not meet its exact contract")


def validate_accessibility(value: dict[str, object], *, passed: bool) -> None:
    """Only counts and fixed rule metadata may cross the private browser boundary."""
    expected = {
        "violations",
        "passed_rule_count",
        "incomplete_rule_count",
        "tags",
        "source_sha256",
        "axe_version",
        "current_access_status",
        "directory_search_status",
        "keyboard_input_to_submit_focus",
        "invalid_plan_alert",
        "invalid_plan_get_count",
        "localized_state_count",
        "assurance",
        "frame_count",
    }
    if set(value) != expected or value["tags"] != AXE_TAGS or value["axe_version"] != AXE_VERSION:
        raise RuntimeError("Exact native accessibility scanner contract required")
    digest = value["source_sha256"]
    violations = value["violations"]
    if (
        not isinstance(digest, str)
        or not re.fullmatch("[0-9a-f]{64}", digest)
        or not isinstance(violations, list)
    ):
        raise RuntimeError("Safe scanner digest and rule list required")
    for item in cast(list[object], violations):
        rule = record(item)
        if (
            set(rule) != {"rule", "impact", "affected_nodes"}
            or not isinstance(rule["rule"], str)
            or not re.fullmatch("[a-z0-9-]{1,100}", rule["rule"])
            or rule["impact"] not in {None, "minor", "moderate", "serious", "critical"}
            or type(rule["affected_nodes"]) is not int
            or rule["affected_nodes"] < 1
        ):
            raise RuntimeError("Safe axe rule metadata required")
    for key in (
        "passed_rule_count",
        "incomplete_rule_count",
        "invalid_plan_get_count",
        "localized_state_count",
        "frame_count",
    ):
        if type(value[key]) is not int or cast(int, value[key]) < 0:
            raise RuntimeError("Actual nonnegative accessibility counts required")
    if (
        value["current_access_status"] != 200
        or value["directory_search_status"] != 200
        or value["keyboard_input_to_submit_focus"] is not True
        or value["invalid_plan_alert"] is not True
        or value["invalid_plan_get_count"] != 0
        or value["localized_state_count"] != 7
        or value["assurance"] != "AL2"
        or value["frame_count"] != 0
        or (passed and (violations or cast(int, value["passed_rule_count"]) <= 0))
    ):
        raise RuntimeError("Native keyboard, HTTP or accessibility qualification failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = run(args.state, args.output)
    print(json.dumps(value, indent=2))
    raise SystemExit(0 if value["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
