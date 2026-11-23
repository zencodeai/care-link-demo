"""Trainer-owned fictional scenarios in separate durable storage."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import psycopg
from care_link_contracts import validate_contract
from care_link_domain import Actor, AuthorityPort, CipherPort, ManualError, admit_training_artifact
from care_link_domain import canonical_training as canonical
from care_link_domain import exercise_training_fixture as exercise
from care_link_domain import training_digest as digest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .receiver import Record

TrainingPermit = Callable[[Actor, str, str | None, str], bool]


class TrainingService:
    def __init__(
        self,
        dsn: str,
        authority: AuthorityPort,
        permit: TrainingPermit,
        cipher: CipherPort,
        *,
        artifact: bytes,
        artifact_digest: str,
        admitted_trainers: frozenset[str],
        complete_immediate_fixtures: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        settings = conninfo_to_dict(dsn)
        if settings.get("sslmode") != "verify-full" or not settings.get("sslrootcert"):
            raise ValueError("Training storage requires explicit verified TLS")
        key_ref = getattr(cipher, "key_ref", None)
        if not isinstance(key_ref, str) or not key_ref:
            raise ValueError("Training recording requires explicit encryption custody")
        self.cipher, self.content_key_ref = cipher, key_ref
        self.artifact_digest = admit_training_artifact(artifact, artifact_digest)
        self.dsn = dsn
        self.authority, self.permit, self.clock = authority, permit, clock
        self.admitted_trainers = frozenset(admitted_trainers)
        self.complete_immediate_fixtures = complete_immediate_fixtures

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection[Record]]:
        try:
            with psycopg.Connection[Record].connect(
                self.dsn, row_factory=dict_row, connect_timeout=1
            ) as connection:
                connection.execute("SET LOCAL statement_timeout='750ms'")
                yield connection
        except psycopg.OperationalError as error:
            raise ManualError("training.store_unavailable", 503) from error
        except psycopg.Error as error:
            raise ManualError("training.transaction_unavailable", 503) from error

    def _authorize(
        self, actor: Actor, action: str, target: str | None, request_digest: str
    ) -> None:
        if actor.account_id not in self.admitted_trainers or actor.role != "trainer":
            raise ManualError("training.trainer_required")
        current = self.authority.current(actor)
        now = self.clock()
        deadline = min(
            actor.expires_at,
            current.expires_at,
            actor.request_deadline or actor.expires_at,
            current.request_deadline or current.expires_at,
        )
        if (
            current.account_id != actor.account_id
            or current.role != actor.role
            or current.identity_revision != actor.identity_revision
            or current.role_revision != actor.role_revision
            or current.browser_session_digest != actor.browser_session_digest
            or current.transport_generation != actor.transport_generation
            or not current.mfa
            or not now - timedelta(minutes=5) < current.auth_time <= now + timedelta(seconds=1)
            or now >= deadline
            or self.permit(current, action, target, request_digest) is not True
            or self.clock() >= deadline
        ):
            raise ManualError("training.current_authority_required")

    @staticmethod
    def _own(
        connection: psycopg.Connection[Record], actor: Actor, scenario_id: str, *, lock: bool
    ) -> Record:
        row = connection.execute(
            "SELECT * FROM training.scenario WHERE id=%s AND owner_id=%s FOR UPDATE"
            if lock
            else "SELECT * FROM training.scenario WHERE id=%s AND owner_id=%s",
            (scenario_id, actor.account_id),
        ).fetchone()
        if row is None:
            raise ManualError("training.scenario_unavailable", 404)
        return row

    def _fixture(self, row: Record) -> Record:
        fixture = cast(Record, row["fixture"])
        validate_contract("ScenarioCreate", fixture)
        if fixture["artifact_digest"] != self.artifact_digest or self.clock() >= cast(
            datetime, row["created_at"]
        ) + timedelta(days=7):
            raise ManualError("training.scenario_unavailable", 404)
        return fixture

    def scenario_read(self, actor: Actor, scenario_id: str) -> Record:
        validate_contract("Id", scenario_id)
        request = digest({"scenario_id": scenario_id})
        self._authorize(actor, "scenario_read", scenario_id, request)
        with self._connection() as connection:
            row = self._own(connection, actor, scenario_id, lock=False)
            fixture = self._fixture(row)
            view: Record = {
                "id": scenario_id,
                "revision": str(row["revision"]),
                "state": row["state"],
                "artifact_digest": fixture["artifact_digest"],
                "evidence_digest": row["evidence_digest"],
            }
            self._audit_access(connection, actor, scenario_id, "scenario", digest(view))
            self._authorize(actor, "scenario_read", scenario_id, request)
        return view

    def scenario_create(self, actor: Actor, key: str, fixture: Record) -> Record:
        validate_contract("ScenarioCreate", fixture)
        frozen = cast(Record, json.loads(json.dumps(fixture)))
        if frozen["artifact_digest"] != self.artifact_digest:
            raise ManualError("training.artifact_unavailable", 422)
        return self._command(actor, key, "scenario_create", None, frozen)

    def scenario_stop(self, actor: Actor, key: str, scenario_id: str, data: Record) -> Record:
        return self._transition(actor, key, "scenario_stop", scenario_id, data)

    def complete_fixture(self, actor: Actor, key: str, scenario_id: str, data: Record) -> Record:
        """Run the pinned, offline fixture at the current revision in a separate transaction."""
        return self._transition(actor, key, "scenario_exercise", scenario_id, data)

    def _transition(
        self, actor: Actor, key: str, action: str, scenario_id: str, data: Record
    ) -> Record:
        validate_contract("RevisionCommand", data)
        validate_contract("Id", scenario_id)
        return self._command(
            actor, key, action, scenario_id, {"expected_revision": data["expected_revision"]}
        )

    def _command(
        self, actor: Actor, key: str, action: str, target: str | None, data: Record
    ) -> Record:
        validate_contract("Id", key)
        request = digest({"target": target, "data": data})
        self._authorize(actor, action, target, request)
        with self._connection() as connection:
            namespace = ":".join((actor.account_id, action, key))
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (namespace,))
            old = connection.execute(
                "SELECT * FROM training.operation WHERE owner_id=%s AND action=%s AND id=%s",
                (actor.account_id, action, key),
            ).fetchone()
            if old is not None:
                if old["request_digest"] != request:
                    raise ManualError("manual.idempotency_conflict", 409)
                view = cast(Record, old["view"])
                self._fixture(self._own(connection, actor, str(view["resource_id"]), lock=False))
            else:
                scenario_id = target or str(uuid4())
                revision = 1
                if target is None:
                    self._create_row(connection, actor, scenario_id, data)
                else:
                    revision = self._transition_row(connection, actor, scenario_id, action, data)
                audit = str(uuid4())
                view = cast(
                    Record,
                    {
                        "operation_id": key,
                        "resource_id": scenario_id,
                        "revision": str(revision),
                        "audit_ref": audit,
                        "state": "committed",
                    },
                )
                validate_contract("CommandResult", view)
                connection.execute(
                    "INSERT INTO training.operation VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (key, actor.account_id, action, request, Jsonb(view), audit, self.clock()),
                )
            self._authorize(actor, action, target, request)
        return view

    def _capture(self, scenario_id: str, fixture: Record) -> tuple[str, str, str]:
        projection = exercise(scenario_id, fixture)
        return (
            self.cipher.encrypt(canonical(projection).decode()),
            self.content_key_ref,
            digest(projection),
        )

    def _create_row(
        self, connection: psycopg.Connection[Record], actor: Actor, scenario_id: str, data: Record
    ) -> None:
        immediate = self.complete_immediate_fixtures and data["fixture_mode"] != "delay"
        ciphertext, content_key, observed = (
            self._capture(scenario_id, data) if immediate else (None, None, None)
        )
        connection.execute(
            "INSERT INTO training.scenario (id,owner_id,revision,state,fixture,created_at,"
            "projection_ciphertext,content_key_ref,evidence_digest) "
            "VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s)",
            (
                scenario_id,
                actor.account_id,
                "completed" if immediate else "running",
                Jsonb(data),
                self.clock(),
                ciphertext,
                content_key,
                observed,
            ),
        )

    def _transition_row(
        self,
        connection: psycopg.Connection[Record],
        actor: Actor,
        scenario_id: str,
        action: str,
        data: Record,
    ) -> int:
        row = self._own(connection, actor, scenario_id, lock=True)
        fixture = self._fixture(row)
        if str(row["revision"]) != data["expected_revision"] or row["state"] != "running":
            raise ManualError("manual.revision_conflict", 409)
        revision = cast(int, row["revision"]) + 1
        complete = action == "scenario_exercise"
        ciphertext, content_key, observed = (
            self._capture(scenario_id, fixture) if complete else (None, None, None)
        )
        connection.execute(
            "UPDATE training.scenario SET revision=%s,state=%s,"
            "projection_ciphertext=%s,content_key_ref=%s,evidence_digest=%s WHERE id=%s",
            (
                revision,
                "completed" if complete else "stopped",
                ciphertext,
                content_key,
                observed,
                scenario_id,
            ),
        )
        return revision

    def recording(self, actor: Actor, scenario_id: str) -> tuple[Record, Record, datetime]:
        """Return an owner-scoped completed evidence projection and its expiry anchor."""
        validate_contract("Id", scenario_id)
        request = digest({"scenario_id": scenario_id, "projection": "recording"})
        self._authorize(actor, "scenario_read", scenario_id, request)
        with self._connection() as connection:
            row = self._own(connection, actor, scenario_id, lock=False)
            fixture = self._fixture(row)
            ciphertext = row["projection_ciphertext"]
            if (
                row["state"] != "completed"
                or not isinstance(ciphertext, str)
                or row["content_key_ref"] != self.content_key_ref
            ):
                raise ManualError("training.recording_unavailable", 404)
            opened: object = json.loads(self.cipher.decrypt(ciphertext))
            if not isinstance(opened, dict) or row["evidence_digest"] != digest(
                cast(Record, opened)
            ):
                raise ManualError("training.corrupt_recording", 503)
            result = cast(Record, opened)
            self._audit_access(connection, actor, scenario_id, "recording", digest(result))
            self._authorize(actor, "scenario_read", scenario_id, request)
        return fixture, result, cast(datetime, row["created_at"])

    def _audit_access(
        self,
        connection: psycopg.Connection[Record],
        actor: Actor,
        scenario_id: str,
        projection: str,
        output_digest: str,
    ) -> None:
        connection.execute(
            "INSERT INTO training.access VALUES (%s,%s,%s,%s,%s,%s)",
            (str(uuid4()), actor.account_id, scenario_id, projection, output_digest, self.clock()),
        )

    def expire_recordings(self) -> int:
        """Remove up to one batch of past-due active recording ciphertext."""
        with self._connection() as connection:
            row = connection.execute("SELECT training.expire_recordings() AS count").fetchone()
            if row is None:
                raise ManualError("training.expiry_unavailable", 503)
            return cast(int, row["count"])
