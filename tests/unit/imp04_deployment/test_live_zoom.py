"""Native zoom boundary tests; synthetic mocks never establish live browser evidence."""

import hashlib
import json
import shutil
import subprocess
from uuid import uuid4

import pytest

from tools.imp04_verification import live_zoom as zoom


@pytest.fixture
def setup(tmp_path, monkeypatch):
    private = tmp_path / "private"
    state = private / "prior"
    sessions = state / "sessions"
    sessions.mkdir(parents=True)
    for path in (private, state, sessions):
        path.chmod(0o700)
    monkeypatch.setattr(zoom, "PRIVATE", private)
    actors = {}
    for slot, role in zoom.ACTORS.items():
        actors[slot] = {
            "accountId": str(uuid4()),
            "role": role,
            "password": "NEVER_TRANSFER_PASSWORD",
            "totpSecret": "NEVER_TRANSFER_OTP",
        }
        cookie = {
            "domain": "plans.localhost",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "name": "__Host-care-link-session",
            "value": "PRIVATE_REAL_COOKIE_" + slot,
            "expires": 2000000000,
            "sameSite": "Lax",
        }
        zoom.write(
            sessions / (slot + ".json"),
            json.dumps(
                {
                    "cookies": [
                        cookie,
                        {**cookie, "domain": "id.plans.localhost", "value": "NEVER_TRANSFER_IDP"},
                    ],
                    "origins": [
                        {"origin": zoom.MAIN, "localStorage": [{"secret": "NEVER_TRANSFER"}]}
                    ],
                }
            ),
        )
    zoom.write(private / "browser.json", json.dumps({"mainOrigin": zoom.MAIN, "actors": actors}))
    return state, private / "zoom.json", actors


def observation(actor, slot, locale):
    return {
        "slot": slot,
        "account_id": actor["accountId"],
        "role": actor["role"],
        "locale": locale,
        "status": "passed",
        "stage": "complete",
        "baseline": {"dpr": 1, "width": 1440, "outer": 1440, "pinch": 1, "height": 1100},
        "enlarged": {"dpr": 2, "width": 720, "outer": 1440, "pinch": 1, "height": 550},
        "keyboard_tabs": 15,
        "control_reachable": True,
        "session_status": 200,
        "scroll_end": 1000,
        "scroll_limit": 1000,
        "profile_removed": True,
        "zoom_restored": True,
        "current_access_completed_200": True,
        "initial_session_status": 200,
        "directory_status": 200,
        "cleanup": {
            "status": "passed",
            "zoom_restored": True,
            "page_unloaded": True,
            "context_closed": True,
            "profile_removed": True,
            "failures": [],
        },
        "accessibility": {
            "violations": [],
            "passed_rule_count": 25,
            "incomplete_rule_count": 1,
            "tags": zoom.AXE_TAGS,
            "source_sha256": "d" * 64,
            "axe_version": zoom.AXE_VERSION,
            "current_access_status": 200,
            "directory_search_status": 200,
            "keyboard_input_to_submit_focus": True,
            "invalid_plan_alert": True,
            "invalid_plan_get_count": 0,
            "localized_state_count": 7,
            "assurance": "AL2",
            "frame_count": 0,
        },
    }


def runner(monkeypatch, actors, *, edit=None, returncode=0):
    calls = []
    monkeypatch.setattr(
        zoom,
        "axe_bundle",
        lambda: {
            "axe_source": "PUBLIC_AXE_SOURCE",
            "axe_sha256": "d" * 64,
            "axe_version": zoom.AXE_VERSION,
        },
    )
    monkeypatch.setattr(
        zoom,
        "inspect_container",
        lambda name: {
            "Id": "a" * 64,
            "NetworkSettings": {
                "Networks": {
                    zoom.PREFIX + "-ingress": {"NetworkID": "b" * 64, "IPAddress": "172.29.47.10"}
                }
            },
        },
    )
    monkeypatch.setattr(zoom.shutil, "which", lambda name: "/fixed/docker")

    def invoke(argv, **kwargs):
        calls.append((argv, kwargs))
        rows = [
            observation(actor, slot, locale)
            for slot, actor in actors.items()
            for locale in zoom.LOCALES
        ]
        value = {"version": zoom.VERSION, "observations": rows}
        if edit:
            edit(value)
        return subprocess.CompletedProcess(argv, returncode, json.dumps(value))

    monkeypatch.setattr(zoom.subprocess, "run", invoke)
    return calls


def test_only_genuine_main_origin_cookies_and_bindings_transfer(setup):
    state, _, actors = setup
    source = zoom.payload(state)
    encoded = json.dumps(source)
    assert "NEVER_TRANSFER" not in encoded
    for item in source["actors"]:
        assert item["account_id"] == actors[item["slot"]]["accountId"]
        saved = json.loads((state / "sessions" / (item["slot"] + ".json")).read_text())
        assert item["cookies"] == [saved["cookies"][0]]


@pytest.mark.parametrize("part", ["private", "state", "sessions", "file"])
def test_private_owner_only_boundary_precedes_docker(setup, monkeypatch, part):
    state, output, _ = setup
    path = {
        "private": state.parent,
        "state": state,
        "sessions": state / "sessions",
        "file": state / "sessions/pid.json",
    }[part]
    path.chmod(0o755 if path.is_dir() else 0o644)
    monkeypatch.setattr(zoom, "inspect_container", lambda _: pytest.fail("must not inspect"))
    with pytest.raises(ValueError, match="Owner-only"):
        zoom.run(state, output)


def test_session_symlink_is_refused(setup):
    state, _, _ = setup
    path = state / "sessions/pid.json"
    destination = path.with_suffix(".saved")
    path.rename(destination)
    path.symlink_to(destination)
    with pytest.raises(ValueError, match="Owner-only"):
        zoom.payload(state)


@pytest.mark.parametrize("mutation", ["role", "uuid", "shared", "tls", "cookie"])
def test_exact_issued_bindings_and_secure_cookie_guards(setup, mutation):
    state, _, _ = setup
    path = state.parent / "browser.json"
    value = json.loads(path.read_text())
    if mutation == "role":
        value["actors"]["carer"]["role"] = "operator"
    elif mutation == "uuid":
        value["actors"]["carer"]["accountId"] = value["actors"]["carer"]["accountId"].upper()
    elif mutation == "shared":
        value["actors"]["carer"]["accountId"] = value["actors"]["pid"]["accountId"]
    elif mutation == "tls":
        value["ignoreHTTPSErrors"] = True
    else:
        saved = state / "sessions/carer.json"
        cookies = json.loads(saved.read_text())
        cookies["cookies"][0]["secure"] = False
        saved.write_text(json.dumps(cookies))
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        zoom.payload(state)


def test_single_immutable_exec_keeps_cookie_values_only_on_stdin(setup, monkeypatch):
    state, output, actors = setup
    calls = runner(monkeypatch, actors)
    result = zoom.run(state, output)
    assert result["status"] == "passed" and len(result["observations"]) == 8
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:5] == ["/fixed/docker", "exec", "--interactive", "a" * 64, "node"]
    assert "PRIVATE_REAL_COOKIE" not in json.dumps(argv)
    assert "PRIVATE_REAL_COOKIE" in kwargs["input"]
    assert json.loads(kwargs["input"])["address_pin"] == "172.29.47.10"
    assert "PUBLIC_AXE_SOURCE" not in json.dumps(argv)
    assert json.loads(kwargs["input"])["axe_source"] == "PUBLIC_AXE_SOURCE"
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert output.stat().st_mode & 0o777 == 0o600
    assert "PRIVATE_REAL_COOKIE" not in output.read_text()


@pytest.mark.parametrize(
    "change",
    ["dpr", "width", "outer", "pinch", "keyboard", "cleanup", "identity", "extra", "nonfinite"],
)
def test_false_native_zoom_evidence_is_rejected(setup, monkeypatch, change):
    state, output, actors = setup

    def edit(value):
        row = value["observations"][0]
        if change in {"dpr", "width", "outer", "pinch"}:
            row["enlarged"][change] *= 1.5
        elif change == "keyboard":
            row["keyboard_tabs"] = 81
        elif change == "cleanup":
            row["profile_removed"] = False
        elif change == "identity":
            row["account_id"] = str(uuid4())
        elif change == "extra":
            row["private_body"] = "forbidden"
        else:
            row["enlarged"]["dpr"] = float("nan")

    runner(monkeypatch, actors, edit=edit)
    with pytest.raises(RuntimeError):
        zoom.run(state, output)
    assert not output.exists()


def test_failure_stays_failed_and_original_evidence_never_overwritten(setup, monkeypatch):
    state, output, actors = setup

    def edit(value):
        value["observations"][0] = {
            **{
                key: value["observations"][0][key]
                for key in ("slot", "account_id", "role", "locale", "profile_removed", "cleanup")
            },
            "status": "failed",
            "stage": "identity",
        }

    calls = runner(monkeypatch, actors, edit=edit)
    assert zoom.run(state, output)["status"] == "failed"
    first = output.read_bytes()
    with pytest.raises(ValueError, match="New absolute"):
        zoom.run(state, output)
    assert len(calls) == 1 and output.read_bytes() == first


def test_process_failure_suppresses_private_diagnostics(setup, monkeypatch):
    state, output, actors = setup
    runner(monkeypatch, actors, returncode=1)
    with pytest.raises(RuntimeError, match="private diagnostics suppressed"):
        zoom.run(state, output)
    assert not output.exists()


def test_script_uses_real_settings_strict_tls_and_owned_profile_disposal():
    assert "chrome://settings/appearance" in zoom.SCRIPT
    assert "zoom.selectOption('2')" in zoom.SCRIPT
    assert "ignoreHTTPSErrors:false" in zoom.SCRIPT
    assert "launchPersistentContext(profile" in zoom.SCRIPT
    assert "fs.mkdtempSync('/tmp/imp04-native-zoom-')" in zoom.SCRIPT
    assert "fs.chmodSync(profile,0o700)" in zoom.SCRIPT
    assert "fs.rmSync(profile" in zoom.SCRIPT
    assert "process.umask(0o077)" in zoom.SCRIPT
    assert "context.setDefaultNavigationTimeout(10000)" in zoom.SCRIPT
    assert "--host-resolver-rules=MAP plans.localhost " in zoom.SCRIPT
    assert "credentials:'same-origin'" in zoom.SCRIPT
    assert "AbortSignal.timeout(10000)" in zoom.SCRIPT
    assert "page.request" not in zoom.SCRIPT
    for substitute in ("setDeviceMetricsOverride", "setPageScaleFactor", "style.zoom", "Control++"):
        assert substitute not in zoom.SCRIPT


@pytest.mark.parametrize("mutation", ["network", "outside", "ipv6", "network_address", "broadcast"])
def test_address_pin_requires_exact_shared_owned_ingress_network(mutation):
    browser = {
        "NetworkSettings": {
            "Networks": {
                zoom.PREFIX + "-ingress": {"NetworkID": "b" * 64, "IPAddress": "172.29.47.20"}
            }
        }
    }
    ingress = json.loads(json.dumps(browser))
    link = ingress["NetworkSettings"]["Networks"][zoom.PREFIX + "-ingress"]
    assert zoom.address_pin(browser, ingress) == "172.29.47.20"
    if mutation == "network":
        link["NetworkID"] = "c" * 64
    else:
        link["IPAddress"] = {
            "outside": "172.29.48.20",
            "ipv6": "::1",
            "network_address": "172.29.47.0",
            "broadcast": "172.29.47.255",
        }[mutation]
    with pytest.raises(ValueError):
        zoom.address_pin(browser, ingress)


def test_remote_deadline_closes_current_context_stops_launches_and_cleans_own_profile():
    # Execute only a fake browser/fs in a local JS VM; no browser or Docker is invoked.
    harness = r"""
const fs = require('node:fs'), vm = require('node:vm');
const source = JSON.parse(fs.readFileSync(0,'utf8'));
let timer, launches=0, closed=0, removed=0, cleared=0, mask;
const context = {
  close:async () => {closed++;},
  setDefaultTimeout:() => timer(), setDefaultNavigationTimeout:() => {},
  addCookies:async () => {throw Error('closed');}
};
const fakefs = {
  readFileSync:() => JSON.stringify(source.payload),
  mkdtempSync:() => {launches++;return '/tmp/imp04-native-zoom-owned';},
  chmodSync:() => {}, rmSync:() => {removed++;}
};
vm.runInNewContext(source.script, {
  require:name => name === 'node:fs' ? fakefs : name === 'node:crypto' ? require(name) : {
    chromium:{launchPersistentContext:async () => context}},
  process:{umask:value => {mask=value;}},
  setTimeout:(callback, delay) => {if(delay!==210000)throw Error('budget');timer=callback;},
  clearTimeout:() => {cleared++;},
  console:{log:text => console.log(JSON.stringify({
    result:JSON.parse(text),launches,closed,removed,cleared,mask}))}
});
"""
    actors = [
        {"slot": slot, "account_id": str(uuid4()), "role": role}
        for slot, role in zoom.ACTORS.items()
    ]
    result = subprocess.run(  # noqa: S603 - fixed local VM with fake browser and filesystem
        [shutil.which("node") or "node", "-e", harness],
        input=json.dumps(
            {
                "script": zoom.SCRIPT,
                "payload": {
                    "version": zoom.VERSION,
                    "actors": actors,
                    "locales": zoom.LOCALES,
                    "axe_source": "fake scanner",
                    "axe_sha256": hashlib.sha256(b"fake scanner").hexdigest(),
                    "axe_version": zoom.AXE_VERSION,
                },
            }
        ),
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    value = json.loads(result.stdout)
    assert value["launches"] == value["removed"] == value["cleared"] == 1
    assert value["closed"] >= 1 and value["mask"] == 0o077
    rows = value["result"]["observations"]
    assert len(rows) == 8
    assert all(row["status"] == "failed" and row["stage"] == "deadline" for row in rows)
    assert rows[0]["profile_removed"] is True
    assert not any(row["profile_removed"] for row in rows[1:])


@pytest.mark.parametrize(
    "mutation",
    [
        "violations",
        "no_passes",
        "incomplete",
        "status",
        "focus",
        "invalid_alert",
        "invalid_get",
        "labels",
        "assurance",
        "frames",
        "tags",
        "sha",
        "private",
    ],
)
def test_incomplete_or_false_accessibility_evidence_cannot_pass(setup, monkeypatch, mutation):
    state, output, actors = setup

    def edit(value):
        data = value["observations"][0]["accessibility"]
        changes = {
            "violations": (
                "violations",
                [{"rule": "color-contrast", "impact": "serious", "affected_nodes": 2}],
            ),
            "no_passes": ("passed_rule_count", 0),
            "incomplete": ("incomplete_rule_count", -1),
            "status": ("directory_search_status", 503),
            "focus": ("keyboard_input_to_submit_focus", False),
            "invalid_alert": ("invalid_plan_alert", False),
            "invalid_get": ("invalid_plan_get_count", 1),
            "labels": ("localized_state_count", 6),
            "assurance": ("assurance", "AL1"),
            "frames": ("frame_count", 1),
            "tags": ("tags", ["wcag2a"]),
            "sha": ("source_sha256", "e" * 64),
            "private": ("html", "private node markup"),
        }
        key, replacement = changes[mutation]
        data[key] = replacement

    runner(monkeypatch, actors, edit=edit)
    with pytest.raises(RuntimeError):
        zoom.run(state, output)
    assert not output.exists()


def test_failed_axe_retains_only_safe_rule_metadata(setup, monkeypatch):
    state, output, actors = setup

    def edit(value):
        row = value["observations"][0]
        row.update(status="failed", stage="axe_scan")
        row["accessibility"]["violations"] = [
            {"rule": "color-contrast", "impact": "serious", "affected_nodes": 2}
        ]

    runner(monkeypatch, actors, edit=edit)
    result = zoom.run(state, output)
    assert result["status"] == "failed"
    assert result["observations"][0]["accessibility"]["violations"][0]["affected_nodes"] == 2
    assert result["not_run"] == ["human_visual_review", "manual_screen_reader"]
    assert result["watchdog"]["context_close"] == "best_effort"


def test_installed_scanner_is_resolved_via_pinned_playwright_dependency():
    bundle = zoom.axe_bundle()
    assert bundle["axe_version"] == "4.14.0"
    assert len(bundle["axe_source"]) > 100_000
    assert bundle["axe_sha256"] == hashlib.sha256(bundle["axe_source"].encode()).hexdigest()
    assert (
        bundle["axe_sha256"] == "20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878"
    )


def test_scanner_reader_does_not_echo_loader_failure(monkeypatch):
    monkeypatch.setattr(
        zoom.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1, "PRIVATE_UNTRUSTED_DIAGNOSTIC"),
    )
    with pytest.raises(RuntimeError, match="diagnostics suppressed"):
        zoom.axe_bundle()


@pytest.mark.parametrize("field", ["zoom_restored", "current_access_completed_200"])
def test_locale_completion_requires_measured_zoom_restoration_and_full_refresh(
    setup, monkeypatch, field
):
    state, output, actors = setup

    def edit(value):
        value["observations"][0][field] = False

    runner(monkeypatch, actors, edit=edit)
    with pytest.raises(RuntimeError, match="Native zoom or keyboard qualification"):
        zoom.run(state, output)
    assert not output.exists()


def test_locale_controller_waits_for_refresh_restores_metrics_and_unloads():
    assert "row.current_access_completed_200 = true" in zoom.SCRIPT
    assert "await page.waitForFunction(workspaceReady" in zoom.SCRIPT
    assert "Math.abs(devicePixelRatio-before.dpr)<.01" in zoom.SCRIPT
    assert "Math.abs(innerWidth-before.width)<=1" in zoom.SCRIPT
    assert "row.zoom_restored = row.cleanup.zoom_restored = true" in zoom.SCRIPT
    assert "await page.goto('about:blank',{waitUntil:'load'})" in zoom.SCRIPT


def test_ready_predicate_handles_actual_controls_wrapper_and_requires_enabled_visible_control():
    harness = r"""
const fs=require('node:fs'), vm=require('node:vm'), {JSDOM}=require('jsdom');
const prefix=JSON.parse(fs.readFileSync(0,'utf8')).split('(async () => {')[0];
const dom=new JSDOM('<section aria-labelledby="plans-title"><p role="status">Ready</p>'+
  '<div><button>Check access</button></div></section>');
const context=vm.createContext({document:dom.window.document,
  require:name => name==='node:fs' ? {readFileSync:()=> '{}'} :
    name==='node:crypto' ? require(name) : {}, process:{umask:()=> {}}});
vm.runInContext(prefix,context);
const check=()=> vm.runInContext(
  'workspaceReady({notices:["Ready"],controlName:"Check access"})',context);
const button=dom.window.document.querySelector('button');
const wrapper=button.parentElement;
const values=[dom.window.document.querySelector('section > button')===null,check()];
button.disabled=true; values.push(check()); button.disabled=false;
wrapper.setAttribute('hidden',''); values.push(check()); wrapper.removeAttribute('hidden');
wrapper.setAttribute('inert',''); values.push(check()); wrapper.removeAttribute('inert');
dom.window.document.querySelector('p').textContent='Pending';values.push(check());
console.log(JSON.stringify(values));
"""
    result = subprocess.run(  # noqa: S603 - local DOM regression, no browser or Docker
        [shutil.which("node") or "node", "-e", harness],
        cwd=zoom.REPO,
        input=json.dumps(zoom.SCRIPT),
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == [True, True, False, False, False, False]


def test_failure_diagnostics_are_fixed_metadata_and_remain_failed(setup, monkeypatch):
    state, output, actors = setup

    def edit(value):
        value["observations"][0].update(
            status="failed",
            stage="keyboard",
            substage="wait_ready",
            error_category="driver_timeout",
        )

    runner(monkeypatch, actors, edit=edit)
    value = zoom.run(state, output)
    assert value["status"] == "failed"
    assert value["observations"][0]["substage"] == "wait_ready"


@pytest.mark.parametrize("field", ["substage", "error_category", "directory_status"])
def test_failure_metadata_never_reflects_arbitrary_error_text(setup, monkeypatch, field):
    state, output, actors = setup

    def edit(value):
        value["observations"][0].update(
            status="failed",
            stage="keyboard",
            substage="wait_ready",
            error_category="driver_timeout",
        )
        value["observations"][0][field] = "PRIVATE_RAW_EXCEPTION"

    runner(monkeypatch, actors, edit=edit)
    with pytest.raises(RuntimeError):
        zoom.run(state, output)
    assert not output.exists()


@pytest.mark.parametrize("mode", ["success", "first_failure_and_cleanup_failure"])
def test_eight_sequential_owned_contexts_preserve_first_failure_and_isolate_cleanup(mode):
    # Real lifecycle/controller code, fake qualification/browser/fs: no live operation.
    harness = r"""
const fs=require('node:fs'),vm=require('node:vm');
const source=JSON.parse(fs.readFileSync(0,'utf8'));
let profiles=0,active=0,maxActive=0,closed=0,removed=0,restores=0,cleared=0;
const trace=[];
const fakefs={readFileSync:()=>JSON.stringify(source.payload),
  mkdtempSync:()=>{profiles++;return '/tmp/imp04-native-zoom-'+profiles;},chmodSync:()=>{},
  rmSync:profile=>{removed++;trace.push(['remove',profile]);}};
const chromium={launchPersistentContext:async profile=>{
  if(active)throw Error('overlapping contexts');active++;maxActive=Math.max(maxActive,active);
  const id=profiles;let pages=0;trace.push(['launch',profile]);
  const zoom={locator:()=>({count:async()=>1}),selectOption:async()=>{
    restores++;trace.push(['restore',profile]);
    if(source.mode!=='success'&&id===2){const e=Error('private cleanup text');
      e.name='TimeoutError';throw e;}}};
  return {setDefaultTimeout:()=>{},setDefaultNavigationTimeout:()=>{},addCookies:async()=>{},
    newPage:async()=>++pages===1?{goto:async()=>{},locator:()=>zoom}:{
      waitForFunction:async()=>{},goto:async()=>{trace.push(['unload',profile]);
        if(source.mode!=='success'&&id===2){const e=Error('private unload text');
          e.name='TimeoutError';throw e;}}},
    close:async()=>{active--;closed++;trace.push(['close',profile]);}};
}};
const context=vm.createContext({require:name=>name==='node:fs'?fakefs:
  name==='node:crypto'?require(name):{chromium},process:{umask:()=>{}},
  setTimeout:()=>1,clearTimeout:()=>{cleared++;},console:{log:text=>console.log(JSON.stringify({
    result:JSON.parse(text),profiles,maxActive,closed,removed,restores,cleared,trace}))}});
const index=source.script.indexOf('(async () => {');
vm.runInContext(source.script.slice(0,index),context);
context.qualify=async(page,zoom,actor,locale,row,state)=>{
  state.baseline={dpr:1,width:1440};
  if(source.mode!=='success'&&profiles===2){
    row.directory_status=503;context.failure(row,{name:'QualificationAssertion'},'directory_search','http_status');
  } else {row.status='passed';row.stage='complete';}
};
vm.runInContext(source.script.slice(index),context);
"""
    actors = [
        {"slot": slot, "account_id": str(uuid4()), "role": role, "cookies": []}
        for slot, role in zoom.ACTORS.items()
    ]
    result = subprocess.run(  # noqa: S603 - fixed local lifecycle VM with fake browser/fs
        [shutil.which("node") or "node", "-e", harness],
        cwd=zoom.REPO,
        input=json.dumps(
            {
                "script": zoom.SCRIPT,
                "mode": mode,
                "payload": {
                    "version": zoom.VERSION,
                    "actors": actors,
                    "locales": zoom.LOCALES,
                    "axe_source": "fake scanner",
                    "axe_sha256": hashlib.sha256(b"fake scanner").hexdigest(),
                    "axe_version": zoom.AXE_VERSION,
                },
            }
        ),
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    value = json.loads(result.stdout)
    assert value["profiles"] == value["closed"] == value["removed"] == value["restores"] == 8
    assert value["maxActive"] == value["cleared"] == 1
    rows = value["result"]["observations"]
    assert len(rows) == 8 and all(row["profile_removed"] for row in rows)
    if mode == "success":
        assert all(
            row["status"] == "passed" and row["cleanup"]["status"] == "passed" for row in rows
        )
    else:
        failed = rows[1]
        assert failed["status"] == "failed" and failed["stage"] == "directory_search"
        assert failed["substage"] == "http_status" and failed["directory_status"] == 503
        assert failed["cleanup"]["status"] == "failed"
        assert [entry["stage"] for entry in failed["cleanup"]["failures"]] == [
            "restore_zoom",
            "unload",
        ]
        assert all(row["status"] == "passed" for index, row in enumerate(rows) if index != 1)
        assert (
            "private cleanup text" not in result.stdout
            and "private unload text" not in result.stdout
        )


@pytest.mark.parametrize(
    "field", ["context_closed", "page_unloaded", "profile_removed", "zoom_restored"]
)
def test_passing_row_requires_each_actual_cleanup_step(setup, monkeypatch, field):
    state, output, actors = setup
    runner(
        monkeypatch,
        actors,
        edit=lambda value: value["observations"][0]["cleanup"].update({field: False}),
    )
    with pytest.raises(RuntimeError, match="Complete successful cleanup"):
        zoom.run(state, output)
    assert not output.exists()
