-- Apply to a dedicated synthetic training database, separate from the receiver and Data.
CREATE SCHEMA training;
REVOKE ALL ON SCHEMA training FROM PUBLIC;
CREATE ROLE care_link_training_runtime NOLOGIN;
GRANT USAGE ON SCHEMA training TO care_link_training_runtime;
CREATE TABLE training.scenario (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    revision bigint NOT NULL CHECK (revision > 0),
    state text NOT NULL CHECK (state IN ('running', 'stopped', 'completed')),
    fixture jsonb NOT NULL,
    projection_ciphertext text,
    content_key_ref text,
    evidence_digest text CHECK (evidence_digest ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    expired_at timestamptz,
    CHECK ((state = 'completed') = (evidence_digest IS NOT NULL)),
    CHECK ((projection_ciphertext IS NOT NULL) = (content_key_ref IS NOT NULL)),
    CHECK ((state = 'completed' AND expired_at IS NULL) = (projection_ciphertext IS NOT NULL)),
    CHECK (expired_at IS NULL OR (state = 'completed' AND expired_at >= created_at + interval '7 days'))
);
CREATE TABLE training.operation (
    id uuid NOT NULL,
    owner_id uuid NOT NULL,
    action text NOT NULL CHECK (action IN ('scenario_create', 'scenario_stop', 'scenario_exercise')),
    request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    view jsonb NOT NULL,
    audit_id uuid NOT NULL UNIQUE,
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (owner_id, action, id)
);
CREATE TABLE training.access (
    id uuid PRIMARY KEY,
    principal_id uuid NOT NULL,
    scenario_id uuid NOT NULL REFERENCES training.scenario(id),
    projection text NOT NULL CHECK (projection IN ('scenario', 'recording')),
    output_digest text NOT NULL CHECK (output_digest ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL
);
CREATE INDEX training_expiring_captures ON training.scenario (created_at)
    WHERE projection_ciphertext IS NOT NULL;
GRANT SELECT, INSERT ON training.scenario TO care_link_training_runtime;
GRANT UPDATE (revision, state, projection_ciphertext, content_key_ref, evidence_digest, expired_at)
    ON training.scenario TO care_link_training_runtime;
GRANT SELECT, INSERT ON training.operation TO care_link_training_runtime;
GRANT INSERT ON training.access TO care_link_training_runtime;

-- The database clock bounds removal even if a caller supplies a future time.
CREATE FUNCTION training.expire_recordings() RETURNS integer
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, training
AS $$
    WITH due AS (
        SELECT id FROM training.scenario
        WHERE projection_ciphertext IS NOT NULL AND created_at <= now() - interval '7 days'
        ORDER BY created_at, id
        LIMIT 100
        FOR UPDATE SKIP LOCKED
    ), expired AS (
        UPDATE training.scenario
        SET projection_ciphertext = NULL, content_key_ref = NULL, expired_at = now()
        WHERE id IN (SELECT id FROM due)
        RETURNING id
    )
    SELECT count(*)::integer FROM expired
$$;
REVOKE ALL ON FUNCTION training.expire_recordings() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION training.expire_recordings() TO care_link_training_runtime;
