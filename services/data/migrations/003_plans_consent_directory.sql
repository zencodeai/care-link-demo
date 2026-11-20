-- IMP-04 additive schema. Separate migration custody; no runtime DDL/delegation admission.
CREATE SCHEMA plans;
CREATE SCHEMA consent;
CREATE SCHEMA knowledge;
REVOKE ALL ON SCHEMA plans,consent,knowledge FROM PUBLIC;
GRANT USAGE ON SCHEMA plans,consent,knowledge TO care_link_data_runtime,care_link_backup;

CREATE TABLE plans.plan (
 id uuid PRIMARY KEY, subject_id uuid NOT NULL REFERENCES core.subject_guard(subject_id),
 session_id uuid NOT NULL REFERENCES core.session(id), revision bigint NOT NULL CHECK(revision>=1),
 state text NOT NULL CHECK(state IN ('active','retired')),
 created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, retired_at timestamptz,
 CHECK((state='retired')=(retired_at IS NOT NULL))
);
CREATE INDEX plan_subject_state ON plans.plan(subject_id,state);
CREATE TABLE plans.field (
 id uuid PRIMARY KEY, plan_id uuid NOT NULL REFERENCES plans.plan(id),
 subject_id uuid NOT NULL REFERENCES core.subject_guard(subject_id),
 session_id uuid NOT NULL REFERENCES core.session(id),
 field_key text NOT NULL CHECK(field_key IN ('plan.warning_signs','plan.strategies',
 'plan.responders','plan.medication_report','plan.advance_wishes','plan.contacts',
 'plan.substitute_decision_maker')),
 revision bigint NOT NULL CHECK(revision>=1), value_ciphertext text NOT NULL,
 author_id uuid NOT NULL REFERENCES control.principal_guard(principal_id), source jsonb,
 verification text NOT NULL CHECK(verification IN ('unverified','verified','disputed')),
 supersedes_id uuid REFERENCES plans.field(id), effective_at timestamptz NOT NULL,
 safety_relevant boolean NOT NULL, UNIQUE(plan_id,field_key,revision)
);
CREATE TABLE plans.review_work (
 id uuid PRIMARY KEY, plan_id uuid NOT NULL REFERENCES plans.plan(id),
 field_id uuid NOT NULL REFERENCES plans.field(id), state text NOT NULL CHECK(state='pending'),
 created_at timestamptz NOT NULL
);
CREATE TABLE consent.delegation (
 id uuid PRIMARY KEY, subject_id uuid NOT NULL REFERENCES core.subject_guard(subject_id),
 grantor_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 purposes text[] NOT NULL CHECK(cardinality(purposes)>0),
 fields text[] NOT NULL CHECK(cardinality(fields)>0),
 expires_at timestamptz NOT NULL, revoked_at timestamptz
);
CREATE TABLE consent.current_grant (
 grant_id uuid PRIMARY KEY, subject_id uuid NOT NULL REFERENCES core.subject_guard(subject_id),
 session_id uuid NOT NULL REFERENCES core.session(id),
 recipient_id uuid NOT NULL, recipient_kind text NOT NULL CHECK(recipient_kind IN ('account','service')),
 recipient jsonb NOT NULL, purpose text NOT NULL CHECK(purpose IN ('plan','referral','follow_up')),
 fields text[] NOT NULL CHECK(cardinality(fields) BETWEEN 1 AND 32),
 grantor_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 authority_proof_id uuid NOT NULL, basis text NOT NULL CHECK(basis IN ('self','explicit_demo_delegation')),
 scope_hash text NOT NULL CHECK(scope_hash ~ '^[0-9a-f]{64}$'), scope jsonb NOT NULL,
 revision bigint NOT NULL CHECK(revision>=1), grantor_identity_revision bigint NOT NULL,
 grantor_role_revision bigint NOT NULL, subject_revision bigint NOT NULL,
 effective_at timestamptz NOT NULL, expires_at timestamptz NOT NULL, revoked_at timestamptz,
 CHECK(expires_at>effective_at)
);
CREATE INDEX consent_current_scope ON consent.current_grant(subject_id,recipient_id,purpose);
CREATE TABLE consent.event (
 id uuid PRIMARY KEY, grant_id uuid NOT NULL REFERENCES consent.current_grant(grant_id),
 subject_id uuid NOT NULL REFERENCES core.subject_guard(subject_id),
 kind text NOT NULL CHECK(kind IN ('grant','revoke','expire')), sequence bigint NOT NULL CHECK(sequence>=1),
 scope_hash text NOT NULL CHECK(scope_hash ~ '^[0-9a-f]{64}$'), created_at timestamptz NOT NULL,
 UNIQUE(grant_id,sequence)
);
CREATE FUNCTION consent.restrict_grant_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL
 OR NEW.revision<>OLD.revision+1
 OR (to_jsonb(NEW)-'revoked_at'-'revision') IS DISTINCT FROM
    (to_jsonb(OLD)-'revoked_at'-'revision') THEN
  RAISE EXCEPTION 'grant scope is immutable; only first revocation may update projection';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER grant_scope_immutable BEFORE UPDATE ON consent.current_grant
 FOR EACH ROW EXECUTE FUNCTION consent.restrict_grant_update();

CREATE TABLE knowledge.service_version (
 id uuid PRIMARY KEY, service_id uuid NOT NULL, revision bigint NOT NULL CHECK(revision>=1),
 environment text NOT NULL CHECK(environment='demo'), population text NOT NULL CHECK(population='synthetic'),
 created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
 facts jsonb NOT NULL, sources jsonb NOT NULL,
 state text NOT NULL CHECK(state IN ('verified','stale','quarantined','suspended')),
 verified_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 source_revision bigint NOT NULL CHECK(source_revision>=0),
 freshness_class text NOT NULL CHECK(freshness_class IN ('structural','operational','near_realtime')),
 artifact_digest text NOT NULL CHECK(artifact_digest ~ '^[0-9a-f]{64}$'),
 UNIQUE(service_id,revision)
);
CREATE TABLE knowledge.service_guard (
 service_id uuid PRIMARY KEY, current_revision bigint NOT NULL CHECK(current_revision>=0),
 suspension_revision bigint NOT NULL CHECK(suspension_revision>=0), suspended boolean NOT NULL,
 FOREIGN KEY(service_id,current_revision) REFERENCES knowledge.service_version(service_id,revision)
 DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE knowledge.quarantine (
 id uuid PRIMARY KEY, service_id uuid NOT NULL, artifact_digest text NOT NULL,
 payload_digest text NOT NULL, reason text NOT NULL, created_at timestamptz NOT NULL
);
GRANT SELECT,INSERT,UPDATE ON plans.plan,plans.review_work,consent.current_grant,
 knowledge.service_guard TO care_link_data_runtime;
GRANT SELECT,INSERT ON plans.field,consent.event,knowledge.service_version,
 knowledge.quarantine TO care_link_data_runtime;
GRANT SELECT ON consent.delegation TO care_link_data_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA plans,consent,knowledge TO care_link_backup;

-- Metadata discovery is internal only; exact scope is rechecked under existing
-- global/principal/subject/session guards before any permitted content projection.
ALTER TABLE plans.plan ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans.plan FORCE ROW LEVEL SECURITY;
CREATE POLICY plan_metadata ON plans.plan FOR SELECT TO care_link_data_runtime USING(true);
CREATE POLICY plan_insert ON plans.plan FOR INSERT TO care_link_data_runtime
 WITH CHECK(session_id::text=current_setting('care_link.session',true));
CREATE POLICY plan_update ON plans.plan FOR UPDATE TO care_link_data_runtime
 USING(session_id::text=current_setting('care_link.session',true))
 WITH CHECK(session_id::text=current_setting('care_link.session',true));
ALTER TABLE plans.field ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans.field FORCE ROW LEVEL SECURITY;
CREATE POLICY plan_field_scope ON plans.field TO care_link_data_runtime
 USING(session_id::text=current_setting('care_link.session',true))
 WITH CHECK(session_id::text=current_setting('care_link.session',true));
ALTER TABLE consent.current_grant ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent.current_grant FORCE ROW LEVEL SECURITY;
CREATE POLICY consent_metadata ON consent.current_grant FOR SELECT TO care_link_data_runtime USING(true);
CREATE POLICY consent_insert ON consent.current_grant FOR INSERT TO care_link_data_runtime
 WITH CHECK(session_id::text=current_setting('care_link.session',true));
CREATE POLICY consent_update ON consent.current_grant FOR UPDATE TO care_link_data_runtime
 USING(session_id::text=current_setting('care_link.session',true))
 WITH CHECK(session_id::text=current_setting('care_link.session',true));
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['plans.plan','plans.field','consent.current_grant'] LOOP
  EXECUTE format('CREATE POLICY imp04_backup ON %s FOR SELECT TO care_link_backup USING(true)',t);
 END LOOP;
END $$;

-- Plan snapshots retain their own explicit retirement anchor. Ending a support
-- conversation must not expire an active plan's independent purpose.
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_purpose_check;
ALTER TABLE lifecycle.copy ADD CHECK(purpose IN ('support','plan'));
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_anchor_kind_check;
ALTER TABLE lifecycle.copy ADD CHECK(anchor_kind IN ('last_parent_closed','plan_retired'));

ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_aggregate_type_check;
ALTER TABLE lifecycle.copy ADD CHECK(aggregate_type IN ('session','turn','message','assertion','plan','plan_field'));
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_check1;
ALTER TABLE lifecycle.copy ADD CHECK(expires_at IS NULL OR
 (purpose='support' AND expires_at=anchor_at+interval '7 days') OR
 (purpose='plan' AND expires_at=anchor_at+interval '30 days'));
