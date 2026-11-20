-- IMP-05 additive gateway schema. Receiver storage has separate credentials/schema custody.
CREATE SCHEMA referral;
REVOKE ALL ON SCHEMA referral FROM PUBLIC;
GRANT USAGE ON SCHEMA referral TO care_link_data_runtime,care_link_backup;
CREATE TABLE referral.generation (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id),
 subject_id uuid NOT NULL REFERENCES core.subject_guard(subject_id),
 recipient_service_id uuid NOT NULL REFERENCES knowledge.service_guard(service_id),
 directory_revision bigint NOT NULL, generation bigint NOT NULL CHECK(generation>=1),
 revision bigint NOT NULL CHECK(revision>=1), payload_ciphertext text NOT NULL,
 payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),
 selected jsonb NOT NULL, state text NOT NULL,
 consent_id uuid REFERENCES consent.current_grant(grant_id), review_id uuid, dispatch_id uuid,
 author_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 created_at timestamptz NOT NULL
);
CREATE TABLE referral.review (
 id uuid PRIMARY KEY, referral_id uuid NOT NULL REFERENCES referral.generation(id),
 session_id uuid NOT NULL REFERENCES core.session(id), decision text NOT NULL CHECK(decision IN ('accept','reject')),
 reviewer_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 exact_digest text NOT NULL, source_vector jsonb NOT NULL,
 expires_at timestamptz NOT NULL, revision bigint NOT NULL CHECK(revision>=1)
);
CREATE TABLE referral.dispatch (
 id uuid PRIMARY KEY, referral_id uuid NOT NULL UNIQUE REFERENCES referral.generation(id),
 session_id uuid NOT NULL REFERENCES core.session(id), payload_digest text NOT NULL,
 consent_id uuid NOT NULL REFERENCES consent.current_grant(grant_id),
 review_id uuid NOT NULL REFERENCES referral.review(id), owner_id uuid NOT NULL,
 revision bigint NOT NULL CHECK(revision>=1), state text NOT NULL CHECK(state IN
 ('pending','authorized','attempted','unknown','received','partial','accepted','rejected','cancelled','reconciliation_needed')),
 attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
 receipt_id uuid, receipt jsonb, authorization_id uuid, fence bigint NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL
);
CREATE TABLE referral.authorization (
 id uuid PRIMARY KEY, dispatch_id uuid NOT NULL REFERENCES referral.dispatch(id),
 session_id uuid NOT NULL REFERENCES core.session(id), fence bigint NOT NULL,
 versions jsonb NOT NULL, payload_digest text NOT NULL, consumed_at timestamptz,
 created_at timestamptz NOT NULL, UNIQUE(dispatch_id,fence)
);
CREATE TABLE referral.attempt (
 id uuid PRIMARY KEY, authorization_id uuid NOT NULL UNIQUE REFERENCES referral.authorization(id),
 dispatch_id uuid NOT NULL REFERENCES referral.dispatch(id), session_id uuid NOT NULL,
 fence bigint NOT NULL, created_at timestamptz NOT NULL
);
CREATE FUNCTION referral.immutable_generation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(OLD)-'revision'-'state'-'consent_id'-'review_id'-'dispatch_id') IS DISTINCT FROM
 (to_jsonb(NEW)-'revision'-'state'-'consent_id'-'review_id'-'dispatch_id') THEN
 RAISE EXCEPTION 'referral payload generations are immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_generation BEFORE UPDATE ON referral.generation
 FOR EACH ROW EXECUTE FUNCTION referral.immutable_generation();
CREATE FUNCTION referral.one_use_authorization() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL OR
 (to_jsonb(OLD)-'consumed_at') IS DISTINCT FROM (to_jsonb(NEW)-'consumed_at') THEN
 RAISE EXCEPTION 'dispatch authorization is single use'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER one_use BEFORE UPDATE ON referral.authorization
 FOR EACH ROW EXECUTE FUNCTION referral.one_use_authorization();
GRANT SELECT,INSERT,UPDATE ON referral.generation,referral.dispatch,referral.authorization TO care_link_data_runtime;
GRANT SELECT,INSERT ON referral.review,referral.attempt TO care_link_data_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA referral TO care_link_backup;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['generation','review','dispatch','authorization','attempt'] LOOP
 EXECUTE format('ALTER TABLE referral.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE referral.%I FORCE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY metadata ON referral.%I FOR SELECT TO care_link_data_runtime USING(true)',t);
 EXECUTE format('CREATE POLICY insert_scope ON referral.%I FOR INSERT TO care_link_data_runtime WITH CHECK(session_id::text=current_setting(''care_link.session'',true))',t);
 EXECUTE format('CREATE POLICY update_scope ON referral.%I FOR UPDATE TO care_link_data_runtime USING(session_id::text=current_setting(''care_link.session'',true)) WITH CHECK(session_id::text=current_setting(''care_link.session'',true))',t);
 EXECUTE format('CREATE POLICY backup ON referral.%I FOR SELECT TO care_link_backup USING(true)',t);
 END LOOP;
END $$;
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_aggregate_type_check;
ALTER TABLE lifecycle.copy ADD CHECK(aggregate_type IN ('session','turn','message','assertion','plan','plan_field','referral'));
CREATE TABLE referral.observation (
 id uuid PRIMARY KEY, dispatch_id uuid NOT NULL REFERENCES referral.dispatch(id),
 session_id uuid NOT NULL REFERENCES core.session(id), receipt jsonb,
 safe_reason text CHECK(safe_reason IS NULL OR safe_reason='invalid_receipt'),
 created_at timestamptz NOT NULL
);
GRANT SELECT,INSERT ON referral.observation TO care_link_data_runtime;
GRANT SELECT ON referral.observation TO care_link_backup;
ALTER TABLE referral.observation ENABLE ROW LEVEL SECURITY;
ALTER TABLE referral.observation FORCE ROW LEVEL SECURITY;
CREATE POLICY read_scope ON referral.observation FOR SELECT TO care_link_data_runtime
 USING(session_id::text=current_setting('care_link.session',true));
CREATE POLICY insert_scope ON referral.observation FOR INSERT TO care_link_data_runtime
 WITH CHECK(session_id::text=current_setting('care_link.session',true));
CREATE POLICY backup ON referral.observation FOR SELECT TO care_link_backup USING(true);

-- Referral copies cannot inherit session-only cleanup: uncertain delivery is a live parent.
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_purpose_check;
ALTER TABLE lifecycle.copy ADD CHECK(purpose IN ('support','plan','referral'));
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_anchor_kind_check;
ALTER TABLE lifecycle.copy ADD CHECK(anchor_kind IN ('last_parent_closed','plan_retired','referral_terminal_parent'));
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_check1;
ALTER TABLE lifecycle.copy ADD CHECK(expires_at IS NULL OR
 (purpose IN ('support','referral') AND expires_at=anchor_at+interval '7 days') OR
 (purpose='plan' AND expires_at=anchor_at+interval '30 days'));
