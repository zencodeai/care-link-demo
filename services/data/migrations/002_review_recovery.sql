-- Additive review namespace/recovery metadata. Apply once as the migration owner.
-- Operator run administration has separate custody and cannot edit business rows.
CREATE TABLE core.review_schema_version (
 version text PRIMARY KEY, migration_digest text NOT NULL CHECK(migration_digest ~ '^[0-9a-f]{64}$')
);
CREATE TABLE core.review_run (
 id uuid PRIMARY KEY, environment_id text NOT NULL CHECK(length(environment_id) BETWEEN 1 AND 96),
 scenario text NOT NULL CHECK(scenario='manual-service'), scenario_version text NOT NULL,
 state text NOT NULL CHECK(state IN ('active','closing','closed')),
 revision bigint NOT NULL CHECK(revision>=1), created_at timestamptz NOT NULL,
 closed_at timestamptz
);
CREATE UNIQUE INDEX review_one_active_environment ON core.review_run(environment_id)
 WHERE state IN ('active','closing');
CREATE TABLE core.review_admin_operation (
 operation_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES core.review_run(id),
 command text NOT NULL CHECK(command IN ('create','close')), payload_digest text NOT NULL,
 created_at timestamptz NOT NULL
);
CREATE TABLE core.review_member (
 session_id uuid PRIMARY KEY REFERENCES core.session(id), run_id uuid NOT NULL REFERENCES core.review_run(id)
);
CREATE INDEX review_member_run ON core.review_member(run_id,session_id);
CREATE TABLE core.review_draft (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id),
 principal_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 kind text NOT NULL CHECK(kind IN ('intake','message')), revision bigint NOT NULL CHECK(revision>=1),
 text_ciphertext text NOT NULL, expires_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
 UNIQUE(session_id,principal_id,kind)
);
CREATE TABLE core.review_intent (
 operation_id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id),
 principal_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 kind text NOT NULL CHECK(kind IN ('intake','message')), draft_revision bigint NOT NULL,
 action text NOT NULL CHECK(action IN ('session_turns','message_send')),
 payload_ciphertext text NOT NULL, created_at timestamptz NOT NULL,
 cancelled_at timestamptz CHECK(cancelled_at IS NULL OR cancelled_at>=created_at),
 UNIQUE(session_id,principal_id,kind,draft_revision)
);
GRANT SELECT ON core.review_run,core.review_member TO care_link_data_runtime;
GRANT INSERT ON core.review_member TO care_link_data_runtime;
GRANT SELECT,INSERT,UPDATE ON core.review_draft TO care_link_data_runtime;
GRANT SELECT,INSERT ON core.review_intent TO care_link_data_runtime;
GRANT UPDATE(cancelled_at) ON core.review_intent TO care_link_data_runtime;
CREATE FUNCTION core.review_intent_cancel_once() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.cancelled_at IS NOT NULL OR NEW.cancelled_at IS NULL
 OR (to_jsonb(NEW)-'cancelled_at') IS DISTINCT FROM (to_jsonb(OLD)-'cancelled_at') THEN
  RAISE EXCEPTION 'review intent is immutable except first cancellation';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER review_intent_cancel_once BEFORE UPDATE ON core.review_intent
 FOR EACH ROW EXECUTE FUNCTION core.review_intent_cancel_once();
GRANT SELECT ON core.review_schema_version,core.review_run,core.review_admin_operation,core.review_member,core.review_draft,core.review_intent TO care_link_backup;
ALTER TABLE core.review_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.review_run FORCE ROW LEVEL SECURITY;
CREATE POLICY review_run_scope ON core.review_run FOR SELECT TO care_link_data_runtime
 USING(id::text=current_setting('care_link.review_run',true));
CREATE POLICY review_run_backup ON core.review_run FOR SELECT TO care_link_backup USING(true);
-- Membership contains only routing metadata; gateway must discover it to reject
-- legacy-context reads and to filter rows before paginating. It grants no content access.
ALTER TABLE core.review_member ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.review_member FORCE ROW LEVEL SECURITY;
CREATE POLICY review_member_read ON core.review_member FOR SELECT TO care_link_data_runtime USING(true);
CREATE POLICY review_member_write ON core.review_member FOR INSERT TO care_link_data_runtime
 WITH CHECK(run_id::text=current_setting('care_link.review_run',true)
 AND session_id::text=current_setting('care_link.session',true));
CREATE POLICY review_member_backup ON core.review_member FOR SELECT TO care_link_backup USING(true);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['core.review_draft','core.review_intent'] LOOP
  EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY review_recovery_scope ON %s TO care_link_data_runtime USING '
    '(principal_id::text=current_setting(''care_link.principal'',true) AND '
    '(session_id::text=current_setting(''care_link.session'',true) OR current_setting(''care_link.queue'',true)=''true'')) '
    'WITH CHECK(principal_id::text=current_setting(''care_link.principal'',true) AND '
    'session_id::text=current_setting(''care_link.session'',true))',t);
  EXECUTE format('CREATE POLICY review_recovery_backup ON %s FOR SELECT TO care_link_backup USING(true)',t);
 END LOOP;
END $$;
