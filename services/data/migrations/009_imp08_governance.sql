-- Operational governance. Custody registries are not writable by the gateway.
CREATE SCHEMA governance;
REVOKE ALL ON SCHEMA governance FROM PUBLIC;
GRANT USAGE ON SCHEMA governance TO care_link_data_runtime,care_link_backup;
CREATE TABLE governance.human_registry (
 account_id uuid PRIMARY KEY REFERENCES control.principal_guard(principal_id) ON DELETE CASCADE,
 human_id uuid NOT NULL, authority_classes text[] NOT NULL, active boolean NOT NULL,
 identity_revision bigint NOT NULL CHECK(identity_revision>0)
);
CREATE TABLE governance.approval (
 id uuid PRIMARY KEY, purpose text NOT NULL, request_digest text NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
 approver_account_id uuid NOT NULL REFERENCES control.principal_guard(principal_id) ON DELETE CASCADE,
 approver_human_id uuid NOT NULL, expires_at timestamptz NOT NULL, active boolean NOT NULL, scope jsonb NOT NULL
);
CREATE TABLE governance.signer(id text PRIMARY KEY, public_key text NOT NULL, active boolean NOT NULL);
CREATE TABLE governance.candidate (
 digest text PRIMARY KEY CHECK(digest~'^[0-9a-f]{64}$'), metadata jsonb NOT NULL,
 manifest jsonb NOT NULL, payload text NOT NULL, key_id text NOT NULL REFERENCES governance.signer(id)
);
CREATE TABLE governance.instance (
 instance_id text PRIMARY KEY, boot_id uuid NOT NULL, workload_id text NOT NULL,
 actor_id uuid NOT NULL, healthy boolean NOT NULL, required boolean NOT NULL,
 observed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE governance.exception_rule (
 policy_rule_id text PRIMARY KEY, artifact_digest text NOT NULL, compensating_control_digest text NOT NULL,
 scope jsonb NOT NULL, active boolean NOT NULL
);
CREATE TABLE governance.artifact (
 digest text PRIMARY KEY REFERENCES governance.candidate(digest), kind text NOT NULL, version text NOT NULL,
 state text NOT NULL CHECK(state IN('registered','review_pending','approved','rejected','retired')),
 metadata jsonb NOT NULL, manifest jsonb NOT NULL, change_class text NOT NULL,
 proposer_account_id uuid NOT NULL REFERENCES control.principal_guard(principal_id) ON DELETE CASCADE,
 proposer_human_id uuid NOT NULL, created_at timestamptz NOT NULL, last_activated_at timestamptz
);
CREATE TABLE governance.review (
 id uuid PRIMARY KEY, artifact_digest text NOT NULL REFERENCES governance.artifact(digest),
 authority_class text NOT NULL, reviewer_account_id uuid NOT NULL REFERENCES control.principal_guard(principal_id) ON DELETE CASCADE,
 reviewer_human_id uuid NOT NULL, decision text NOT NULL CHECK(decision IN('accept','reject')),
 evidence_digest text NOT NULL, expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL
);
CREATE TABLE governance.activation (
 id uuid PRIMARY KEY, epoch bigint NOT NULL CHECK(epoch>0), base_epoch bigint NOT NULL,
 bundle_digest text NOT NULL REFERENCES governance.artifact(digest),
 state text NOT NULL CHECK(state IN('proposed','staged','ready','active','rejected','superseded')),
 required_instances text[] NOT NULL, revision bigint NOT NULL CHECK(revision>0),
 effective_at timestamptz NOT NULL, created_at timestamptz NOT NULL, restrictive boolean NOT NULL,
 proposer_account_id uuid NOT NULL REFERENCES control.principal_guard(principal_id) ON DELETE CASCADE
);
CREATE TABLE governance.ack (
 id uuid PRIMARY KEY, activation_id uuid NOT NULL REFERENCES governance.activation(id), instance_id text NOT NULL,
 boot_id uuid NOT NULL, epoch bigint NOT NULL, bundle_digest text NOT NULL,
 status text NOT NULL CHECK(status IN('ready','rejected')), created_at timestamptz NOT NULL,
 UNIQUE(activation_id,instance_id)
);
CREATE TABLE governance.exception (
 id uuid PRIMARY KEY, policy_rule_id text NOT NULL, artifact_digest text NOT NULL, epoch bigint NOT NULL,
 scope jsonb NOT NULL, approver_receipt_id uuid NOT NULL, expires_at timestamptz NOT NULL,
 compensating_control_digest text NOT NULL, created_at timestamptz NOT NULL
);
CREATE TABLE governance.incident (
 id uuid PRIMARY KEY, kind text NOT NULL, severity text NOT NULL, scope jsonb NOT NULL,
 evidence_refs text[] NOT NULL, revision bigint NOT NULL CHECK(revision>0),
 state text NOT NULL CHECK(state IN('open','contained','reviewing','remediated','closed')),
 creator_id uuid NOT NULL REFERENCES control.principal_guard(principal_id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL, review_due_at timestamptz NOT NULL,
 recovery_approval_id uuid, containment_epoch bigint
);
GRANT SELECT ON ALL TABLES IN SCHEMA governance TO care_link_backup;
GRANT SELECT ON governance.human_registry,governance.approval,governance.signer,
 governance.candidate,governance.instance,governance.exception_rule TO care_link_data_runtime;
GRANT SELECT,INSERT,UPDATE ON governance.artifact,governance.activation,governance.ack,
 governance.incident TO care_link_data_runtime;
GRANT SELECT,INSERT ON governance.review,governance.exception TO care_link_data_runtime;
-- Immutable artifact identity/bytes and append-only reviews cannot be rewritten.
CREATE FUNCTION governance.artifact_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF (to_jsonb(OLD)-'state'-'last_activated_at') IS DISTINCT FROM
    (to_jsonb(NEW)-'state'-'last_activated_at') THEN
  RAISE EXCEPTION 'governed artifact bytes and provenance are immutable';
 END IF; RETURN NEW; END $$;
CREATE TRIGGER artifact_immutable BEFORE UPDATE ON governance.artifact
 FOR EACH ROW EXECUTE FUNCTION governance.artifact_immutable();

ALTER TABLE durable.duty_operation DROP CONSTRAINT duty_operation_action_check;
ALTER TABLE durable.duty_operation ADD CHECK(action IN ('identity_revoke','job_execute','lifecycle_due','activation_ack'));
