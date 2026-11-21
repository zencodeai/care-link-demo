-- Optional assistance custody; only the gateway has business-store credentials.
CREATE SCHEMA IF NOT EXISTS assistance;
CREATE TABLE assistance.task (
 id uuid PRIMARY KEY, principal_id uuid NOT NULL, session_id uuid NOT NULL REFERENCES core.session(id),
 body jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE assistance.draft (
 id uuid PRIMARY KEY, principal_id uuid NOT NULL, session_id uuid NOT NULL REFERENCES core.session(id),
 task_id uuid NOT NULL REFERENCES assistance.task(id), body jsonb NOT NULL
);
CREATE TABLE assistance.invocation (
 id uuid PRIMARY KEY, principal_id uuid NOT NULL, session_id uuid NOT NULL REFERENCES core.session(id),
 task_id uuid NOT NULL REFERENCES assistance.task(id), request_digest text NOT NULL,
 body jsonb NOT NULL
);
CREATE TABLE assistance.operation (
 id uuid PRIMARY KEY, principal_id uuid NOT NULL, session_id uuid NOT NULL REFERENCES core.session(id),
 action text NOT NULL, request_digest text NOT NULL, resource_id uuid NOT NULL, kind text NOT NULL,
 response_ciphertext text NOT NULL
);
GRANT USAGE ON SCHEMA assistance TO care_link_data_runtime;
GRANT SELECT, INSERT, UPDATE ON assistance.task, assistance.draft TO care_link_data_runtime;
GRANT SELECT, INSERT ON assistance.invocation, assistance.operation TO care_link_data_runtime;
DO $$ DECLARE name text; BEGIN
 FOR name IN SELECT unnest(ARRAY['task','draft','invocation','operation']) LOOP
  EXECUTE format('ALTER TABLE assistance.%I ENABLE ROW LEVEL SECURITY',name);
  EXECUTE format('ALTER TABLE assistance.%I FORCE ROW LEVEL SECURITY',name);
  EXECUTE format('CREATE POLICY assistance_scope ON assistance.%I USING (principal_id::text=current_setting(''care_link.principal'',true) AND session_id::text=current_setting(''care_link.session'',true)) WITH CHECK (principal_id::text=current_setting(''care_link.principal'',true) AND session_id::text=current_setting(''care_link.session'',true))',name);
 END LOOP;
END $$;
-- Identifier-only lookup is separate from content and exact-session RLS.
CREATE TABLE assistance.locator (
 id uuid PRIMARY KEY, kind text NOT NULL CHECK(kind IN ('task','draft')),
 principal_id uuid NOT NULL, session_id uuid NOT NULL REFERENCES core.session(id)
);
ALTER TABLE assistance.locator ENABLE ROW LEVEL SECURITY;
ALTER TABLE assistance.locator FORCE ROW LEVEL SECURITY;
CREATE POLICY assistance_locator ON assistance.locator
 USING(principal_id::text=current_setting('care_link.principal',true))
 WITH CHECK(principal_id::text=current_setting('care_link.principal',true)
 AND session_id::text=current_setting('care_link.session',true));
GRANT SELECT,INSERT ON assistance.locator TO care_link_data_runtime;

ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_aggregate_type_check;
ALTER TABLE lifecycle.copy ADD CONSTRAINT copy_aggregate_type_check CHECK(
 aggregate_type IN ('session','turn','message','assertion','plan','plan_field','referral',
 'assistance_task','assistance_draft','assistance_observation'));
