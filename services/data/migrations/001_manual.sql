-- Ordered additive initial business schema. Apply as a separate migration owner.
-- Runtime roles never migrate, own tables, inherit owners, or bypass row security.
CREATE ROLE care_link_data_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE ROLE care_link_audit_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE ROLE care_link_backup NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE SCHEMA control;
CREATE SCHEMA core;
CREATE SCHEMA workforce;
CREATE SCHEMA durable;
CREATE SCHEMA audit;
CREATE SCHEMA access;
CREATE SCHEMA recovery;
CREATE SCHEMA lifecycle;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
DO $$ BEGIN EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()); END $$;

CREATE TABLE control.guard (
 key text PRIMARY KEY CHECK (key='demo'), epoch bigint NOT NULL CHECK (epoch>=0),
 bundle_digest text NOT NULL CHECK (bundle_digest ~ '^[0-9a-f]{64}$'),
 serving_generation bigint NOT NULL CHECK (serving_generation>=0),
 mode text NOT NULL CHECK (mode IN ('normal','ai_disabled','restricted','quarantine')),
 restriction_barrier bigint NOT NULL CHECK (restriction_barrier>=0),
 journal_tip_seen bigint NOT NULL CHECK (journal_tip_seen>=0),
 journal_id uuid NOT NULL, journal_generation bigint NOT NULL CHECK (journal_generation>=0)
);
CREATE TABLE control.principal_guard (
 principal_id uuid PRIMARY KEY, identity_revision bigint NOT NULL CHECK (identity_revision>=0),
 role_revision bigint NOT NULL CHECK (role_revision>=0), role text NOT NULL,
 revoked boolean NOT NULL DEFAULT false, source_sequence bigint NOT NULL DEFAULT 0
);
CREATE TABLE core.persona (
 id uuid PRIMARY KEY, environment text NOT NULL CHECK(environment='demo'),
 population text NOT NULL CHECK(population='synthetic'), revision bigint NOT NULL CHECK(revision>=0),
 kind text NOT NULL CHECK(kind IN ('pid','carer','professional_participant')),
 account_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 display_alias text NOT NULL, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);
CREATE TABLE core.subject_guard (
 subject_id uuid PRIMARY KEY REFERENCES core.persona(id),
 authority_revision bigint NOT NULL CHECK(authority_revision>=0),
 delete_state text NOT NULL CHECK(delete_state IN ('active','restricted','deleted'))
);
CREATE TABLE core.session (
 id uuid PRIMARY KEY, environment text NOT NULL CHECK(environment='demo'),
 population text NOT NULL CHECK(population='synthetic'), revision bigint NOT NULL CHECK(revision>=0),
 created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
 persona_id uuid NOT NULL REFERENCES core.persona(id), participant_account_id uuid NOT NULL,
 participant_kind text NOT NULL CHECK(participant_kind IN ('pid','carer','professional_participant')),
 jurisdiction text CHECK(jurisdiction IN ('CA-XX','CA-YY')), locale text NOT NULL CHECK(locale IN ('en-CA','fr-CA')),
 channel text NOT NULL CHECK(channel IN ('web','sms_sim','voice_sim','relay_sim')),
 service_phase text NOT NULL CHECK(service_phase IN ('active','human_requested','queued','worker_assigned','handoff_pending','human_controlled','ended')),
 transport text NOT NULL CHECK(transport IN ('connected','reconnecting','disconnected')),
 owner_id uuid REFERENCES control.principal_guard(principal_id), fixture_id uuid,
 tier text CHECK(tier IN ('T0','T1','T2','T3','T4')),
 unresolved boolean NOT NULL, disclosure_acknowledged boolean NOT NULL DEFAULT false,
 assessment_turns bigint NOT NULL DEFAULT 0 CHECK(assessment_turns>=0), closed_at timestamptz,
 CHECK((service_phase='ended')=(closed_at IS NOT NULL))
);
CREATE INDEX session_persona_phase ON core.session(persona_id,service_phase);
CREATE TABLE core.session_guard (
 session_id uuid PRIMARY KEY REFERENCES core.session(id), access_revision bigint NOT NULL CHECK(access_revision>=0),
 control_epoch bigint NOT NULL CHECK(control_epoch>=0), next_event_seq bigint NOT NULL CHECK(next_event_seq>=0)
);
CREATE TABLE core.session_acl (
 session_id uuid NOT NULL REFERENCES core.session(id), principal_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 purpose text NOT NULL CHECK(purpose IN ('support','observe','interrupt')), fields text[] NOT NULL,
 valid_until timestamptz, revoked_at timestamptz, revision bigint NOT NULL CHECK(revision>=0),
 PRIMARY KEY(session_id,principal_id,purpose)
);
CREATE TABLE core.turn (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id), client_turn_id uuid NOT NULL,
 event_seq bigint NOT NULL, author_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 text_ciphertext text NOT NULL, locale text NOT NULL CHECK(locale IN ('en-CA','fr-CA')),
 assessment_revision bigint NOT NULL CHECK(assessment_revision>=0), created_at timestamptz NOT NULL,
 UNIQUE(session_id,client_turn_id), UNIQUE(session_id,event_seq)
);
CREATE TABLE core.assertion (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id), subject_id uuid NOT NULL REFERENCES core.persona(id),
 revision bigint NOT NULL CHECK(revision>=0), field_key text NOT NULL,
 value_ciphertext text NOT NULL, author_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 verification text NOT NULL CHECK(verification IN ('unverified','verified','disputed')),
 supersedes_id uuid REFERENCES core.assertion(id), effective_at timestamptz NOT NULL, created_at timestamptz NOT NULL
);
CREATE TABLE core.assessment (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id), revision bigint NOT NULL CHECK(revision>=0),
 fixture_id uuid, field_states jsonb NOT NULL, tier_set_digest text NOT NULL CHECK(tier_set_digest ~ '^[0-9a-f]{64}$'),
 tier text NOT NULL CHECK(tier IN ('T0','T1','T2','T3','T4')), hazard_fixture boolean NOT NULL,
 human_reasons text[] NOT NULL, created_at timestamptz NOT NULL, UNIQUE(session_id,revision)
);
CREATE TABLE core.message (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id), revision bigint NOT NULL CHECK(revision>=0),
 sender_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 kind text NOT NULL CHECK(kind IN ('participant','human_authored','approved_template')),
 text_ciphertext text NOT NULL, control_epoch bigint NOT NULL CHECK(control_epoch>=0), created_at timestamptz NOT NULL
);
CREATE INDEX message_order ON core.message(session_id,created_at,id);
CREATE TABLE core.choice (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id), author_id uuid NOT NULL,
 action text NOT NULL CHECK(action IN ('disagree_rationale','decline_option','choose_alternative')),
 service_id uuid, rationale_version text, created_at timestamptz NOT NULL
);
CREATE TABLE workforce.queue_entry (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id), revision bigint NOT NULL CHECK(revision>=0),
 requested_at timestamptz NOT NULL, mode text NOT NULL CHECK(mode IN ('normal','elevated','severe','partner_unavailable','regional_outage')),
 fixture_priority integer NOT NULL CHECK(fixture_priority BETWEEN 0 AND 4), next_review_at timestamptz NOT NULL,
 status text NOT NULL CHECK(status IN ('pending','reserved','accepted','cancelled')),
 created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);
CREATE UNIQUE INDEX queue_one_active ON workforce.queue_entry(session_id) WHERE status IN ('pending','reserved','accepted');
CREATE INDEX queue_order ON workforce.queue_entry(status,fixture_priority,requested_at,id);
CREATE TABLE workforce.assignment (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id), worker_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 revision bigint NOT NULL CHECK(revision>=0), reservation_id uuid NOT NULL UNIQUE, expires_at timestamptz NOT NULL,
 status text NOT NULL CHECK(status IN ('reserved','accepted','connected','released','expired')),
 control_epoch bigint NOT NULL CHECK(control_epoch>=0), accepted_at timestamptz, connected_at timestamptz,
 created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);
CREATE UNIQUE INDEX assignment_one_active ON workforce.assignment(session_id) WHERE status IN ('reserved','accepted','connected');
CREATE TABLE workforce.channel_challenge (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id), assignment_id uuid NOT NULL REFERENCES workforce.assignment(id),
 control_epoch bigint NOT NULL CHECK(control_epoch>=0), expires_at timestamptz NOT NULL, revoked boolean NOT NULL DEFAULT false,
 participant_nonce_hash text, worker_nonce_hash text,
 participant_binding text, worker_binding text,
 participant_generation bigint, worker_generation bigint, evidence_id uuid UNIQUE, created_at timestamptz NOT NULL
);
ALTER TABLE workforce.assignment ADD COLUMN channel_challenge_id uuid REFERENCES workforce.channel_challenge(id);
CREATE UNIQUE INDEX challenge_one_active ON workforce.channel_challenge(session_id) WHERE NOT revoked;
CREATE TABLE workforce.channel_ack (
 id uuid PRIMARY KEY, challenge_id uuid NOT NULL REFERENCES workforce.channel_challenge(id),
 session_id uuid NOT NULL REFERENCES core.session(id), party text NOT NULL CHECK(party IN ('participant','worker')),
 principal_id uuid NOT NULL REFERENCES control.principal_guard(principal_id), browser_binding text NOT NULL,
 transport_generation bigint NOT NULL CHECK(transport_generation>=0),
 identity_revision bigint NOT NULL CHECK(identity_revision>=0), role_revision bigint NOT NULL CHECK(role_revision>=0),
 session_access_revision bigint NOT NULL CHECK(session_access_revision>=0),
 created_at timestamptz NOT NULL,
 UNIQUE(challenge_id,party)
);
CREATE TABLE durable.operation (
 operation_id uuid PRIMARY KEY, principal_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 operation_name text NOT NULL, key uuid NOT NULL, payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),
 state text NOT NULL CHECK(state IN ('committed','rejected','replacement_unavailable')),
 session_id uuid REFERENCES core.session(id), resource_id uuid, result_type text NOT NULL,
 canonical_audit_id uuid NOT NULL, created_at timestamptz NOT NULL,
 UNIQUE(principal_id,operation_name,key)
);
-- Workload duties have their own actor identity, never a human principal FK.
CREATE TABLE durable.duty_operation (
 operation_id uuid PRIMARY KEY, actor_id uuid NOT NULL, workload_id text NOT NULL,
 action text NOT NULL CHECK(action IN ('identity_revoke','job_execute')),
 payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),
 resource_id uuid, revision bigint NOT NULL CHECK(revision>=0),
 canonical_audit_id uuid NOT NULL, created_at timestamptz NOT NULL,
 state text NOT NULL DEFAULT 'committed' CHECK(state IN ('committed','rejected')),
 safe_reason text CHECK(safe_reason IS NULL OR length(safe_reason)<=96)
);
CREATE TABLE durable.duty_nonce (
 nonce uuid PRIMARY KEY, actor_id uuid NOT NULL, operation_id uuid NOT NULL,
 request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$')
);
CREATE TABLE durable.due_job (
 job_id uuid PRIMARY KEY, kind text NOT NULL CHECK(kind='reservation_expiry'),
 aggregate_id uuid NOT NULL REFERENCES workforce.assignment(id),
 session_id uuid NOT NULL REFERENCES core.session(id),
 expected_revision bigint NOT NULL CHECK(expected_revision>=0), fence bigint NOT NULL CHECK(fence>=0),
 original_operation_id uuid NOT NULL, due_at timestamptz NOT NULL, deadline timestamptz NOT NULL,
 state text NOT NULL CHECK(state IN ('pending','completed','superseded')),
 completed_operation_id uuid, CHECK(deadline>due_at)
);
CREATE TABLE control.signal_source (issuer_id text PRIMARY KEY, quarantined boolean NOT NULL);
CREATE TABLE control.signal_head (
 issuer_id text NOT NULL, subject_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 source_sequence bigint NOT NULL CHECK(source_sequence>=0), digest text NOT NULL,
 PRIMARY KEY(issuer_id,subject_id)
);
CREATE TABLE control.signal_receipt (
 issuer_id text NOT NULL, jti uuid NOT NULL, subject_id uuid NOT NULL,
 digest text NOT NULL CHECK(digest ~ '^[0-9a-f]{64}$'), operation_id uuid NOT NULL,
 PRIMARY KEY(issuer_id,jti)
);
CREATE TABLE durable.event (
 session_id uuid NOT NULL REFERENCES core.session(id), sequence bigint NOT NULL CHECK(sequence>=0),
 event_id uuid NOT NULL UNIQUE, type text NOT NULL CHECK(type IN ('session_changed','message_available','queue_changed','resync_required')),
 resource_id uuid NOT NULL, resource_revision bigint NOT NULL CHECK(resource_revision>=0), occurred_at timestamptz NOT NULL,
 PRIMARY KEY(session_id,sequence)
);
CREATE TABLE access.continuation_family (
 id uuid PRIMARY KEY, account_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 root_family_id uuid NOT NULL REFERENCES access.continuation_family(id),
 session_id uuid NOT NULL REFERENCES core.session(id), channel text NOT NULL,
 generation bigint NOT NULL CHECK(generation>=0), status text NOT NULL CHECK(status IN ('active','revoked')),
 revision bigint NOT NULL CHECK(revision>=0), created_at timestamptz NOT NULL
);
CREATE UNIQUE INDEX continuation_one_active_lineage ON access.continuation_family(root_family_id) WHERE status='active';
CREATE TABLE access.continuation_token (
 family_id uuid NOT NULL REFERENCES access.continuation_family(id), generation bigint NOT NULL CHECK(generation>=0),
 token_hash text NOT NULL UNIQUE CHECK(token_hash ~ '^[0-9a-f]{64}$'), expires_at timestamptz NOT NULL,
 consumed_at timestamptz, operation_id uuid NOT NULL,
 PRIMARY KEY(family_id,generation)
);
CREATE TABLE recovery.command (
 command_id uuid PRIMARY KEY, intent_seq bigint NOT NULL UNIQUE, barrier_seq bigint NOT NULL,
 payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'), state text NOT NULL CHECK(state IN ('applied','observed')),
 db_operation_id uuid NOT NULL, applied_at timestamptz NOT NULL
);
CREATE TABLE lifecycle.copy (
 copy_id uuid PRIMARY KEY, subject_id uuid NOT NULL REFERENCES core.persona(id),
 session_id uuid NOT NULL REFERENCES core.session(id), purpose text NOT NULL CHECK(purpose='support'),
 aggregate_type text NOT NULL CHECK(aggregate_type IN ('session','turn','message','assertion')),
 aggregate_id uuid NOT NULL, content_ref text NOT NULL UNIQUE,
 classification text NOT NULL CHECK(classification='synthetic_content'),
 encryption_key_ref text NOT NULL, anchor_kind text NOT NULL CHECK(anchor_kind='last_parent_closed'),
 anchor_at timestamptz, expires_at timestamptz,
 state text NOT NULL CHECK(state IN ('anchor_pending','retained','purged')),
 created_at timestamptz NOT NULL,
 CHECK((state='anchor_pending')=(anchor_at IS NULL AND expires_at IS NULL)),
 CHECK(expires_at IS NULL OR expires_at=anchor_at+interval '7 days')
);
CREATE TABLE lifecycle.dependency (
 parent_copy_id uuid NOT NULL REFERENCES lifecycle.copy(copy_id),
 child_copy_id uuid NOT NULL REFERENCES lifecycle.copy(copy_id),
 reason text NOT NULL CHECK(reason='session_parent'),
 PRIMARY KEY(parent_copy_id,child_copy_id), CHECK(parent_copy_id<>child_copy_id)
);
CREATE TABLE audit.head (
 stream_id text PRIMARY KEY CHECK(stream_id='demo'), next_sequence bigint NOT NULL CHECK(next_sequence>=0),
 digest text NOT NULL CHECK(digest ~ '^[0-9a-f]{64}$')
);
CREATE TABLE audit.event (
 stream_id text NOT NULL REFERENCES audit.head(stream_id), sequence bigint NOT NULL CHECK(sequence>=0),
 event_id uuid NOT NULL UNIQUE, operation_id uuid NOT NULL UNIQUE, principal_id uuid NOT NULL,
 action text NOT NULL, decision text NOT NULL CHECK(decision IN ('PERMIT','DENY')),
 input_digest text NOT NULL CHECK(input_digest ~ '^[0-9a-f]{64}$'), output_digest text NOT NULL CHECK(output_digest ~ '^[0-9a-f]{64}$'),
 versions jsonb NOT NULL, previous_hash text NOT NULL, hash text NOT NULL, created_at timestamptz NOT NULL,
 actor_context jsonb,
 PRIMARY KEY(stream_id,sequence)
);
INSERT INTO audit.head VALUES('demo',1,repeat('0',64));

-- care.audit.v1 uses sorted compact UTF-8 JSON, finite integer authority and
-- decimal-string revisions. Hashes are recomputed inside the narrow append
-- function from persisted metadata, not trusted from the gateway caller.
CREATE FUNCTION audit.canonical_json(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,audit AS $$
 SELECT CASE jsonb_typeof(value)
 WHEN 'object' THEN '{' || COALESCE((
  SELECT string_agg(to_json(key)::text || ':' || audit.canonical_json(item),',' ORDER BY key)
  FROM jsonb_each(value) AS entries(key,item)
 ),'') || '}'
 WHEN 'array' THEN '[' || COALESCE((
  SELECT string_agg(audit.canonical_json(item),',' ORDER BY ordinal)
  FROM jsonb_array_elements(value) WITH ORDINALITY AS items(item,ordinal)
 ),'') || ']'
 ELSE value::text END
$$;
REVOKE ALL ON FUNCTION audit.canonical_json(jsonb) FROM PUBLIC;
CREATE FUNCTION audit.append_event(p_event uuid,p_operation uuid,p_principal uuid,p_action text,p_decision text,
 p_input text,p_output text,p_versions jsonb,p_created timestamptz,p_expected text,p_hash text,
 p_actor_context jsonb DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,audit AS $$
DECLARE h audit.head%ROWTYPE; expected_hash text; encoded jsonb;
BEGIN
 SELECT * INTO STRICT h FROM audit.head WHERE stream_id='demo' FOR UPDATE;
 IF h.digest<>p_expected THEN RAISE EXCEPTION 'audit head conflict'; END IF;
 IF current_setting('care_link.principal',true) IS DISTINCT FROM p_principal::text THEN
  RAISE EXCEPTION 'audit principal mismatch';
 END IF;
 encoded := jsonb_build_object(
  'event_id',p_event::text,'operation_id',p_operation::text,'principal_id',p_principal::text,
  'action',p_action,'decision',p_decision,'input_digest',p_input,'output_digest',p_output,
  'versions',p_versions,'previous_hash',p_expected,
  'created_at',to_char(p_created AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'encoding','care.audit.v1','stream_id','demo','sequence',h.next_sequence::text
 );
 IF p_actor_context IS NOT NULL THEN
  IF p_actor_context->'actor'->>'kind' IS DISTINCT FROM 'workload'
   OR p_actor_context->'actor'->>'actor_id' IS DISTINCT FROM p_principal::text
   OR p_actor_context->'evidence'->>'kind' IS DISTINCT FROM 'workload_duty' THEN
   RAISE EXCEPTION 'audit workload context mismatch';
  END IF;
  encoded := encoded || jsonb_build_object('actor_context',p_actor_context);
 END IF;
 expected_hash := encode(sha256(convert_to(audit.canonical_json(encoded),'UTF8')),'hex');
 IF p_hash IS DISTINCT FROM expected_hash THEN RAISE EXCEPTION 'audit hash mismatch'; END IF;
 INSERT INTO audit.event VALUES('demo',h.next_sequence,p_event,p_operation,p_principal,p_action,p_decision,
  p_input,p_output,p_versions,p_expected,p_hash,p_created,p_actor_context);
 UPDATE audit.head SET next_sequence=next_sequence+1,digest=p_hash WHERE stream_id='demo';
END $$;
REVOKE ALL ON FUNCTION audit.append_event(uuid,uuid,uuid,text,text,text,text,jsonb,timestamptz,text,text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION audit.append_event(uuid,uuid,uuid,text,text,text,text,jsonb,timestamptz,text,text,jsonb) TO care_link_data_runtime;
GRANT USAGE ON SCHEMA core,workforce,control,durable,access,recovery,lifecycle,audit TO care_link_data_runtime;
GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA core,workforce,durable,access,recovery,lifecycle TO care_link_data_runtime;
GRANT SELECT,UPDATE ON control.guard,control.principal_guard TO care_link_data_runtime;
GRANT SELECT,INSERT,UPDATE ON control.signal_source,control.signal_head,control.signal_receipt TO care_link_data_runtime;
GRANT SELECT ON audit.head TO care_link_data_runtime;
GRANT USAGE ON SCHEMA audit TO care_link_audit_reader;
GRANT SELECT ON audit.event,audit.head TO care_link_audit_reader;
GRANT USAGE ON SCHEMA core,workforce,control,durable,access,recovery,lifecycle,audit TO care_link_backup;
GRANT SELECT ON ALL TABLES IN SCHEMA core,workforce,control,durable,access,recovery,lifecycle,audit TO care_link_backup;

-- Scope is set transaction-locally by authenticated gateway code. A compromised
-- gateway can forge this context within its grants; this is defense in depth.
DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['core.session','core.session_guard','core.session_acl','core.turn','core.assertion','core.assessment','core.message','core.choice',
 'lifecycle.copy','workforce.queue_entry','workforce.assignment','workforce.channel_challenge','workforce.channel_ack','durable.event'] LOOP
  EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY',t);
  IF t='core.session' THEN
   EXECUTE format('CREATE POLICY gateway_scope ON %s TO care_link_data_runtime USING (id::text=current_setting(''care_link.session'',true) OR current_setting(''care_link.queue'',true)=''true'') WITH CHECK(id::text=current_setting(''care_link.session'',true))',t);
  ELSE
   EXECUTE format('CREATE POLICY gateway_scope ON %s TO care_link_data_runtime USING (session_id::text=current_setting(''care_link.session'',true) OR current_setting(''care_link.queue'',true)=''true'') WITH CHECK(session_id::text=current_setting(''care_link.session'',true))',t);
  END IF;
  EXECUTE format('CREATE POLICY backup_read ON %s FOR SELECT TO care_link_backup USING (true)',t);
 END LOOP;
END $$;
