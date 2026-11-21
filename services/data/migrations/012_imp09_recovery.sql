-- Separate maintenance custody only. Normal gateway cannot create, alter or
-- certify a recovery target. This is not a network-quarantine substitute.
CREATE TABLE recovery.target_validation (
 target_id uuid PRIMARY KEY, journal_id uuid NOT NULL, journal_generation bigint NOT NULL,
 journal_tip bigint NOT NULL, journal_digest text NOT NULL,
 restriction_barrier bigint NOT NULL, audit_digest text NOT NULL,
 rights_digest text NOT NULL, schema_digest text NOT NULL, artifact_digest text NOT NULL,
 validated_at timestamptz NOT NULL
);
CREATE TABLE recovery.restriction (
 command_id uuid PRIMARY KEY, sequence bigint NOT NULL UNIQUE,
 kind text NOT NULL, payload jsonb NOT NULL, payload_digest text NOT NULL,
 disposition text NOT NULL CHECK(disposition IN ('applied','unresolved'))
);
REVOKE ALL ON recovery.target_validation,recovery.restriction FROM PUBLIC,care_link_data_runtime;
GRANT SELECT ON recovery.target_validation,recovery.restriction TO care_link_backup;
CREATE TABLE recovery.new_principal (
 target_id uuid NOT NULL, principal_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 identity_evidence_id uuid NOT NULL, PRIMARY KEY(target_id,principal_id)
);
REVOKE ALL ON recovery.new_principal FROM PUBLIC,care_link_data_runtime;
GRANT SELECT ON recovery.new_principal TO care_link_backup;

-- Minimal cross-store import: no assignment, connection, story or grants.
CREATE TABLE recovery.help_import (
 help_id uuid PRIMARY KEY, spool_revision bigint NOT NULL CHECK(spool_revision>0),
 local_event_digest text NOT NULL CHECK(local_event_digest~'^[0-9a-f]{64}$'),
 revision bigint NOT NULL CHECK(revision>0), status text NOT NULL CHECK(status IN
 ('requested','accepted_unconnected','cancelled','closed')),
 local_created_at timestamptz NOT NULL, central_reconciled_at timestamptz NOT NULL,
 connection_confirmed boolean NOT NULL DEFAULT false CHECK(NOT connection_confirmed)
);
REVOKE ALL ON recovery.help_import FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON recovery.help_import TO care_link_data_runtime;
GRANT SELECT ON recovery.help_import TO care_link_backup;
CREATE TABLE recovery.help_operation (
 command_id uuid PRIMARY KEY, help_id uuid NOT NULL REFERENCES recovery.help_import(help_id),
 request_digest text NOT NULL, revision bigint NOT NULL, audit_ref uuid NOT NULL
);
REVOKE ALL ON recovery.help_operation FROM PUBLIC;
GRANT SELECT,INSERT ON recovery.help_operation TO care_link_data_runtime;
GRANT SELECT ON recovery.help_operation TO care_link_backup;
