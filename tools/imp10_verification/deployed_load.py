"""Exercise the declared IMP-10 load through actual authenticated browser origins."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from time import monotonic, monotonic_ns, sleep
from typing import Literal, Self
from uuid import UUID, uuid4

import httpx

from tools.imp02_application.prepare import write
from tools.imp03_runtime.config import load, record

from .deployed_fixtures import MAIN_ORIGIN, SCOPE, Record, artifact
from .deployed_journey import Browser, require
from .deployed_timing import Load, Workload

SESSIONS = 10
INFERENCE = 2
PENDING = 8
type Locale = Literal["en-CA", "fr-CA"]
NEEDS: dict[Locale, str] = {
    "en-CA": "In this fictional case, the participant needs housing information.",
    "fr-CA": "Dans ce cas fictif, la personne a besoin de renseignements sur le logement.",
}
DISCLOSURES: dict[str, Record] = json.loads(artifact("config/demo/imp03/disclosures.json"))


def elapsed(start: int) -> float:
    return round((monotonic_ns() - start) / 1_000_000, 3)


class EventStream:
    """Use the serving browser transport and consume only event-frame boundaries."""

    def __init__(self, browser: Browser, path: str, after: str | None = None) -> None:
        self.browser, self.path, self.stop = browser, path, Event()
        self.last_event = after
        self.established = Event()
        self.last_frame = 0.0
        self.disconnects = 0
        self.http_status: int | None = None
        self.frames_seen = 0
        self.last_issue = "none"
        self.thread = Thread(target=self._observe, daemon=True)

    def _observe(self) -> None:
        retry_until = monotonic() + 20
        while not self.stop.is_set():
            headers = {"Accept": "text/event-stream"}
            if self.last_event is not None:
                headers["Last-Event-ID"] = self.last_event
            try:
                with self.browser.client.stream(
                    "GET",
                    MAIN_ORIGIN + self.path + "/events",
                    headers=headers,
                    timeout=httpx.Timeout(8, read=5),
                ) as stream:
                    self.http_status = stream.status_code
                    if stream.status_code != 200:
                        if monotonic() > retry_until:
                            return
                        self.stop.wait(0.2)
                        continue
                    if not stream.headers.get("content-type", "").startswith("text/event-stream"):
                        return
                    for line in stream.iter_lines():
                        if self.stop.is_set():
                            return
                        if line == "event: resync_required":
                            self.last_issue = "resync_required"
                            return
                        if line.startswith("id: "):
                            self.last_event = line.removeprefix("id: ")
                        if line == "" or line.startswith(":"):
                            self.frames_seen += 1
                            self.last_frame = monotonic()
                            self.established.set()
                    self.disconnects += 1
            except httpx.TransportError as error:
                self.last_issue = type(error).__name__
                self.disconnects += 1
                if not self.established.is_set() and monotonic() > retry_until:
                    return
            if self.stop.wait(0.15):
                return

    def active(self) -> bool:
        return (
            self.established.is_set()
            and self.thread.is_alive()
            and monotonic() - self.last_frame < 7
        )

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=6)

    def wait(self) -> None:
        require(
            self.established.wait(12) and self.active(),
            f"Actual {self.browser.role} event stream unavailable: "
            f"http={self.http_status}, frames={self.frames_seen}, issue={self.last_issue}",
        )


@dataclass
class Case:
    actor: Browser = field(repr=False)
    locale: Locale
    actor_sha256: str
    session_id: str
    assignment: Record
    setup_ms: float
    event_cursor: str | None = None
    stream: EventStream | None = field(init=False, default=None, repr=False)

    @property
    def path(self) -> str:
        return "/v1/sessions/" + self.session_id

    def active(self) -> bool:
        return self.stream is not None and self.stream.active()


@dataclass(frozen=True)
class IssuedTask:
    session_id: str
    task_id: str
    arrival_ns: int


@dataclass(frozen=True)
class Peak:
    """Read-only product observations supplied by the deployed operator."""

    connected_session_ids: tuple[str, ...]
    occupied_task_ids: tuple[str, ...]
    pending_task_ids: tuple[str, ...]


def ordered[T, V](values: Sequence[T], action: Callable[[T], V], *, parallel: int = 4) -> list[V]:
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        return list(pool.map(action, values))


def startup_post(actor: Browser, path: str, body: Record, *, key: str | None = None) -> Record:
    operation = key or str(uuid4())
    retriable = ("503 (manual.deadline_exceeded)", "503 (manual.authority_unavailable)")
    for attempt in range(3):
        try:
            return actor.post(path, body, key=operation)
        except RuntimeError as error:
            # Restore the same startup command only. Timing samples retain every first outcome.
            if attempt == 2 or not str(error).endswith(retriable):
                raise
    raise AssertionError("Startup retries returned no result")


def party_ack(
    actor: Browser, case: Case, party: str, challenge_id: object, revision: object
) -> Record:
    challenge = actor.get(case.path + "/workforce/challenge")
    require(
        challenge["party"] == party and challenge["challenge_id"] == challenge_id,
        "Channel challenge escaped the exact session and party",
    )
    return {
        "expected_revision": revision,
        "challenge_id": challenge_id,
        "nonce": challenge["nonce"],
        "transport_generation": challenge["transport_generation"],
        "expected_control_epoch": challenge["control_epoch"],
    }


class TenSessions:
    """Own ten synthetic browser sessions and one exact scoped worker."""

    def __init__(
        self,
        *,
        retain_streams: bool = False,
        resume: Path | None = None,
        active_only: bool = False,
    ) -> None:
        self.resources = ExitStack()
        self.retain_streams = retain_streams
        self.resume = resume
        self.active_only = active_only
        self.streams: list[EventStream] = []
        # Register shutdown before creating browsers so failed login closes every transport.
        self.participants = [Browser(f"{SCOPE}-pid-{index}", "pid") for index in range(1, 11)]
        self.worker = Browser(f"{SCOPE}-worker", "worker")
        for actor in [self.worker, *self.participants]:
            self.resources.callback(actor.close)
        self.worker_id = ""
        self.cases: list[Case] = []
        self.started_at = datetime.now(UTC)

    def __enter__(self) -> Self:
        try:
            self.start()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        for stream in self.streams:
            stream.stop.set()
        try:
            for stream in self.streams:
                stream.close()
        finally:
            self.resources.close()

    def _actor_case(self, data: tuple[int, Browser]) -> Case:
        index, browser = data
        locale: Locale = "en-CA" if index % 2 == 0 else "fr-CA"
        began = monotonic_ns()
        account = browser.get("/v1/auth/session")["account_id"]
        view = startup_post(
            browser,
            "/v1/sessions",
            {
                "tags": {"environment": "demo", "population": "synthetic"},
                "participant_kind": "pid",
                "jurisdiction": "CA-XX",
                "locale": locale,
                "channel": "web",
                "persona_id": None,
                "fixture_id": None,
            },
        )
        path = f"/v1/sessions/{view['id']}"
        disclosure = DISCLOSURES[locale]
        current = startup_post(
            browser,
            path + "/disclosure",
            {
                "expected_revision": view["revision"],
                "template_id": disclosure["id"],
                "template_digest": disclosure["digest"],
                "locale": locale,
                "acknowledged": True,
            },
        )
        queued = startup_post(
            browser,
            path + "/human-request",
            {
                "expected_revision": current["revision"],
                "reason": "user_requested",
            },
        )
        require(
            queued["connection_confirmed"] is False, "Queue receipt falsely confirmed connection"
        )
        reservation = startup_post(
            self.worker,
            path + "/workforce/reserve",
            {
                "expected_revision": queued["revision"],
                "worker_id": self.worker_id,
            },
        )
        assignment = startup_post(
            self.worker,
            path + "/workforce/accept",
            {
                "expected_revision": reservation["revision"],
            },
        )
        scoped = browser.get(path)
        require(
            assignment["state"] == "accepted"
            and scoped["service_phase"] == "worker_assigned"
            and scoped["owner_id"] is None,
            "Workforce acceptance skipped two-party connection evidence",
        )
        return Case(
            browser,
            locale,
            hashlib.sha256(str(account).encode()).hexdigest(),
            str(view["id"]),
            assignment,
            elapsed(began),
        )

    def _stream(self, browser: Browser, path: str, after: str | None = None) -> EventStream:
        stream = EventStream(browser, path, after)
        stream.start()
        self.streams.append(stream)
        return stream

    def _connect_case(self, case: Case, *, seed_source: bool) -> None:
        prepared = startup_post(
            self.worker,
            case.path + "/workforce/prepare-transfer",
            {
                "expected_revision": case.assignment["revision"],
            },
        )
        current = self.worker.get(case.path)
        revision = current["revision"]
        worker_ack = party_ack(self.worker, case, "worker", prepared["challenge_id"], revision)
        first = startup_post(self.worker, case.path + "/workforce/channel-acks", worker_ack)
        require(
            first["state"] == "one_party_acknowledged", "Single ACK falsely confirmed transport"
        )
        pid_ack = party_ack(case.actor, case, "participant", prepared["challenge_id"], revision)
        second = startup_post(case.actor, case.path + "/workforce/channel-acks", pid_ack)
        require(second["state"] == "two_party_confirmed", "Real second ACK did not bind transport")
        view = startup_post(
            self.worker,
            case.path + "/workforce/confirm-transfer",
            {
                "expected_revision": revision,
                "assignment_id": case.assignment["id"],
                "channel_evidence_id": second["evidence_id"],
                "worker_ack_id": first["ack_id"],
                "expected_control_epoch": current["control_epoch"],
            },
        )
        require(
            view["service_phase"] == "human_controlled"
            and view["transport"] == "connected"
            and view["owner_id"] == self.worker_id,
            "Protected worker confirmed neither current human ownership nor connection",
        )
        assignment = record(prepared["assignment"])
        case.assignment = {**assignment, "revision": str(int(str(assignment["revision"])) + 1)}
        if seed_source:
            self._seed_source(case, view)

    def _seed_source(self, case: Case, view: Record) -> None:
        startup_post(
            case.actor,
            case.path + "/assertions",
            {
                "expected_revision": view["revision"],
                "subject_id": view["subject_id"],
                "field": "needs",
                "value": {"kind": "text", "text": NEEDS[case.locale]},
                "supersedes_id": None,
                "effective_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
        )

    def _resume_cohort(self, path: Path) -> None:
        binding = load(path)
        require(
            set(binding) == {actor.username for actor in self.participants},
            "Resume inputs must name the ten existing leased participants",
        )
        for participant in self.participants:
            start = monotonic_ns()
            saved = record(binding[participant.username])
            assignment = record(saved["assignment"])
            session_id = str(saved["session_id"])
            assignment_id = str(assignment["id"])
            revision = str(assignment["revision"])
            cursor = str(saved["event_cursor"])
            require(
                str(UUID(session_id)) == session_id
                and str(UUID(assignment_id)) == assignment_id
                and revision.isdecimal()
                and str(int(revision)) == revision
                and cursor.isascii()
                and cursor.isdecimal()
                and len(cursor) <= 19
                and str(int(cursor)) == cursor
                and int(cursor) <= 2**63 - 1,
                "Noncanonical resume session, assignment or event cursor binding",
            )
            route = "/v1/sessions/" + session_id
            view = participant.get(route)
            assigned = self.worker.get(route)
            expected_scope = (
                view["service_phase"] == "worker_assigned"
                and view["owner_id"] is None
                and view["jurisdiction"] == "CA-XX"
                if self.active_only
                else view["service_phase"] in {"human_controlled", "handoff_pending"}
                and view["owner_id"] == self.worker_id
            )
            require(
                view == assigned and view["id"] == session_id and expected_scope,
                "Resume requires the exact durable scope from both current browsers",
            )
            locale: Locale = "fr-CA" if view["locale"] == "fr-CA" else "en-CA"
            account = participant.get("/v1/auth/session")["account_id"]
            self.cases.append(
                Case(
                    participant,
                    locale,
                    hashlib.sha256(str(account).encode()).hexdigest(),
                    session_id,
                    assignment,
                    elapsed(start),
                    event_cursor=cursor,
                )
            )

    def start(self) -> None:
        for browser in (self.worker, *self.participants):
            browser.login()
        self.worker_id = str(self.worker.get("/v1/auth/session")["account_id"])
        if self.resume is None:
            self.cases = [self._actor_case(item) for item in enumerate(self.participants)]
        else:
            self._resume_cohort(self.resume)
        require(
            len({case.session_id for case in self.cases}) == SESSIONS
            and len({case.actor_sha256 for case in self.cases}) == SESSIONS,
            "Declared load requires ten unique sessions and participant principals",
        )
        worker_stream = self._stream(self.worker, self.cases[0].path, self.cases[0].event_cursor)
        worker_stream.wait()
        if self.active_only:
            if self.resume is None:
                for case in self.cases:
                    self._seed_source(case, case.actor.get(case.path))
            return
        for case in self.cases:
            case.stream = self._stream(case.actor, case.path, case.event_cursor)
            case.stream.wait()
            worker_stream.wait()
            self._connect_case(case, seed_source=self.resume is None)
            if not self.retain_streams and self.resume is None:
                case.stream.close()
                self.streams.remove(case.stream)
        if not self.retain_streams and self.resume is None:
            for case in self.cases:
                after = case.stream.last_event if case.stream is not None else None
                case.stream = self._stream(case.actor, case.path, after)
                case.stream.wait()
                self._connect_case(case, seed_source=False)

    def refresh_streams(self) -> None:
        """Refresh a lost stream from the actor's current protected projection."""
        for prior in tuple(self.streams):
            if prior.active():
                continue
            current = prior.browser.get(prior.path)
            require(
                current["service_phase"]
                == ("worker_assigned" if self.active_only else "human_controlled"),
                "Scoped session changed during the browser stream interruption",
            )
            prior.close()
            self.streams.remove(prior)
            after = None if prior.last_issue == "resync_required" else prior.last_event
            stream = self._stream(prior.browser, prior.path, after)
            stream.wait()
            for case in self.cases:
                if case.stream is prior:
                    case.stream = stream
        require(
            all(stream.active() for stream in self.streams),
            "Protected stream refresh did not establish a simultaneous live cohort",
        )

    def sample(self) -> tuple[float, ...]:
        require(all(stream.active() for stream in self.streams), "A real browser stream was lost")

        def measure(case: Case) -> float:
            start = monotonic_ns()
            view = case.actor.get(case.path)
            current_scope = (
                view["service_phase"] == "worker_assigned" and view["owner_id"] is None
                if self.active_only
                else case.active()
                and view["transport"] == "connected"
                and view["service_phase"] == "human_controlled"
                and view["owner_id"] == self.worker_id
            )
            require(
                current_scope and view["id"] == case.session_id,
                "Load sample lost the exact scoped browser session or expected ownership",
            )
            return elapsed(start)

        durations = ordered(self.cases, measure, parallel=2)
        require(
            all(stream.active() for stream in self.streams),
            "A browser stream was lost during the sample",
        )
        return tuple(durations)

    def manual_delivery(self) -> Record:
        if self.active_only:
            return {"observed": False, "reason": "Fresh two-party transport is unconfirmed"}
        case = self.cases[-1]
        start = monotonic_ns()
        view = self.worker.get(case.path)
        message = "Fictional worker response during protected qualification."
        body = {
            "expected_revision": view["revision"],
            "expected_control_epoch": view["control_epoch"],
            "text": message,
            "accepted_draft_id": None,
        }
        key = str(uuid4())
        sent = self.worker.post(case.path + "/messages", body, key=key)
        repeat = self.worker.post(case.path + "/messages", body, key=key)
        visible = [
            item
            for item in case.actor.get(case.path + "/messages")["items"]
            if item["id"] == sent["id"]
        ]
        require(
            sent["kind"] == "human_authored"
            and sent["sender_id"] == self.worker_id
            and repeat["id"] == sent["id"]
            and len(visible) == 1
            and visible[0]["text"] == message,
            "Protected manual message was not visible exactly once under current scope",
        )
        return {"visible_once": True, "exact_retry": True, "elapsed_ms": elapsed(start)}

    def _schedule(self, case: Case) -> IssuedTask:
        session = self.worker.get(case.path)
        started = monotonic_ns()
        admitted = self.worker.post(
            "/v1/tasks",
            {
                "expected_revision": session["revision"],
                "function": "worker_summary",
                "binding": {"kind": "session", "session_id": case.session_id},
                "scope": {
                    "session_id": case.session_id,
                    "subject_id": None,
                    "purpose": "support",
                    "fields": ["needs"],
                    "recipient_id": None,
                },
                "goal": "prepare_summary",
                "completion": "draft_ready",
                "inputs": [],
            },
        )
        require(
            admitted["human_owner_id"] == self.worker_id
            and admitted["state"] == "scoped"
            and admitted["scope"]["session_id"] == case.session_id,
            "Assistance task response lacks exact actor, queue state or scoped session",
        )
        return IssuedTask(case.session_id, str(admitted["id"]), started)

    def issue_initial_pair(
        self, on_accept: Callable[[IssuedTask], None] | None = None
    ) -> tuple[IssuedTask, IssuedTask]:
        availability = self.worker.get("/v1/assistance")
        require(
            availability["available"] is True and "worker_summary" in availability["functions"],
            "Deployed worker_summary serving admission is unavailable",
        )
        tasks: list[IssuedTask] = []
        for case in self.cases[:INFERENCE]:
            task = self._schedule(case)
            tasks.append(task)
            if on_accept is not None:
                on_accept(task)
        return tasks[0], tasks[1]

    def issue_waiting(self) -> tuple[IssuedTask, ...]:
        return tuple(ordered(self.cases[INFERENCE:], self._schedule))

    def sampled_peak(
        self,
        initial: Sequence[IssuedTask],
        waiting: Sequence[IssuedTask],
        observe: Callable[[], Peak],
        source_bytes: Mapping[str, int],
    ) -> Workload:
        require(not self.active_only, "Report active and confirmed counts separately")
        expected = Peak(
            tuple(sorted(case.session_id for case in self.cases)),
            tuple(sorted(task.task_id for task in initial)),
            tuple(sorted(task.task_id for task in waiting)),
        )
        require(
            len(set(expected.occupied_task_ids) | set(expected.pending_task_ids)) == SESSIONS,
            "Ten distinct accepted assistance task ids required",
        )
        start, finish = observe(), observe()
        require(
            start == expected and finish == expected, "Exact deployed 10/2/8 state was not observed"
        )
        durations = self.sample()
        require(observe() == expected, "Peak changed during protected participant reads")
        scheduled = sorted([*initial, *waiting], key=lambda task: task.arrival_ns)
        require(
            set(source_bytes) == {task.task_id for task in scheduled}
            and all(type(size) is int and size > 0 for size in source_bytes.values()),
            "Exact measured source-byte counts required for every admitted task",
        )
        first = scheduled[0].arrival_ns
        locales: dict[str, Locale] = {case.session_id: case.locale for case in self.cases}
        return Workload(
            peak=Load(
                connected_sessions=SESSIONS,
                occupied_inference_slots=INFERENCE,
                unique_pending_tasks=PENDING,
            ),
            session_reads_ms=durations,
            arrival_offsets_ms=tuple(
                round((task.arrival_ns - first) / 1_000_000, 3) for task in scheduled
            ),
            locales=tuple(locales[task.session_id] for task in scheduled),
            channel="web",
            source_bytes_per_task=tuple(source_bytes[task.task_id] for task in scheduled),
        )

    def task_states(self, tasks: Sequence[IssuedTask]) -> list[Record]:
        states: list[Record] = []
        for task in tasks:
            view = self.worker.get("/v1/tasks/" + task.task_id)
            require(
                view["id"] == task.task_id and view["human_owner_id"] == self.worker_id,
                "Task observation escaped the admitted task and worker",
            )
            states.append(
                {
                    "task_id": task.task_id,
                    "state": view["state"],
                    "safe_reason": view["safe_reason"],
                    "steps_used": view["steps_used"],
                    "tools_used": view["tools_used"],
                }
            )
        return states

    def cancel_waiting(self, tasks: Sequence[IssuedTask]) -> None:
        def cancel(task: IssuedTask) -> None:
            route = "/v1/tasks/" + task.task_id
            observed = self.worker.get(route)
            require(observed["state"] == "scoped", "Cancel only this verified waiting work")
            cancelled = self.worker.post(
                route + "/cancel", {"expected_revision": observed["revision"]}
            )
            require(cancelled["state"] == "cancelled", "Owned waiting task did not cancel")

        ordered(tasks, cancel)

    def manual_receipt(self) -> Record:
        durations = self.sample()
        delivery = self.manual_delivery()
        return {
            "scope": "Protected Main workload with ten synthetic participants and one worker",
            "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "started_at": self.started_at.isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "declared_sessions": SESSIONS,
            "active_scoped_sessions": len(self.cases),
            "connected_sessions": 0 if self.active_only else len(self.cases),
            "distinct_participant_bindings": sorted(case.actor_sha256 for case in self.cases),
            "session_ids": sorted(case.session_id for case in self.cases),
            "locale_counts": {
                locale: sum(case.locale == locale for case in self.cases) for locale in NEEDS
            },
            "live_browser_streams": len(self.streams),
            "resumed_existing_handoffs": self.resume is not None,
            "admission": (
                "Ten independent active browsers and one live worker stream; no two-party claim"
                if self.active_only
                else "Exact two-party transfers retain established streams when current"
                if self.retain_streams
                else "Exact two-party transfers followed by verified SSE reconnection"
            ),
            "stream_reconnect_counts": [stream.disconnects for stream in self.streams],
            "protected_session_reads_ms": list(durations),
            "setup_ms_per_session": [case.setup_ms for case in self.cases],
            "manual_delivery": delivery,
            "occupied_inference_slots": None,
            "unique_pending_tasks": None,
        }


def controlled(lane: TenSessions, directory: Path, max_rounds: int) -> None:
    """Serve fixed, owner-signalled phases while the authenticated streams remain open."""
    require(1 <= max_rounds <= 7, "Unsupported qualification round count")
    directory.mkdir(mode=0o700, exist_ok=False)
    require(directory.stat().st_uid == os.getuid(), "Unexpected qualification controller owner")

    def receipt(name: str, result: object) -> None:
        write(directory / (name + ".json"), (json.dumps(result, indent=2) + "\n").encode())

    receipt(
        "admitted",
        {
            "active_scoped_session_ids": sorted(case.session_id for case in lane.cases),
            "human_controlled_session_ids": []
            if lane.active_only
            else sorted(case.session_id for case in lane.cases),
        },
    )
    lane.refresh_streams()
    receipt("ready", lane.manual_receipt())
    print("Ten actual scoped browser sessions are ready.", flush=True)
    deadline = monotonic() + 240
    completed: list[int] = []
    for number in range(1, max_rounds + 1):
        prefix = f"round-{number:02d}-"
        initial: tuple[IssuedTask, IssuedTask] | None = None
        waiting: tuple[IssuedTask, ...] | None = None
        seen: set[str] = set()
        while monotonic() < deadline and not (directory / "stop").exists():
            armed = {
                phase
                for phase in ("pair", "waiting", "sample", "status", "manual", "cancel")
                if phase not in seen and (directory / (prefix + phase)).is_file()
            }
            if initial is None and "pair" in armed:

                def record_acceptance(task: IssuedTask, prefix: str = prefix) -> None:
                    receipt(prefix + "accepted-" + task.session_id, asdict(task))

                initial = lane.issue_initial_pair(record_acceptance)
                receipt(prefix + "pair", [asdict(task) for task in initial])
                seen.add("pair")
            if initial is not None and waiting is None and "waiting" in armed:
                waiting = lane.issue_waiting()
                receipt(prefix + "waiting", [asdict(task) for task in waiting])
                seen.add("waiting")
            if waiting is not None and "sample" in armed:
                receipt(prefix + "sample", {"session_reads_ms": list(lane.sample())})
                seen.add("sample")
            if initial is not None and "status" in armed:
                receipt(prefix + "status", lane.task_states(initial))
                seen.add("status")
            if initial is not None and "manual" in armed:
                receipt(prefix + "manual", lane.manual_delivery())
                seen.add("manual")
            if waiting is not None and "cancel" in armed:
                lane.cancel_waiting(waiting)
                receipt(prefix + "cancel", {"cancelled": len(waiting), "phases": sorted(seen)})
                completed.append(number)
                break
            sleep(0.15)
        else:
            break
    receipt("stopped", {"rounds_completed": completed, "owner_stop": (directory / "stop").exists()})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retain-streams", action="store_true")
    parser.add_argument("--control", type=Path)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--active-only", action="store_true")
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    os.umask(0o077)
    require(not args.output.exists(), "Receipt must bind a fresh synthetic workload")
    with TenSessions(
        retain_streams=args.retain_streams,
        resume=args.resume,
        active_only=args.active_only,
    ) as workload:
        if args.control:
            controlled(workload, args.control, args.rounds)
            result = json.loads((args.control / "ready.json").read_text())
        else:
            workload.refresh_streams()
            result = workload.manual_receipt()
    with args.output.open("x", encoding="utf-8") as file:
        file.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
