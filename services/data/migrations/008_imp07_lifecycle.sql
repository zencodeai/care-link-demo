-- IMP-07: scoped follow-up, own-data rights, retention holds and copy evidence.
CREATE SCHEMA care;
CREATE SCHEMA rights;
REVOKE ALL ON SCHEMA care,rights FROM PUBLIC;
GRANT USAGE ON SCHEMA care,rights TO care_link_data_runtime,care_link_backup;
CREATE TABLE care.post_crisis_event (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id),
 actor_id uuid NOT NULL, source_event_id uuid NOT NULL, occurred_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL, revision bigint NOT NULL CHECK(revision>0),
 UNIQUE(session_id,source_event_id), CHECK(occurred_at<=created_at)
);
CREATE TABLE care.follow_up (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id), subject_id uuid NOT NULL,
 recipient_account_id uuid NOT NULL REFERENCES control.principal_guard(principal_id),
 contact_grant_id uuid NOT NULL REFERENCES consent.current_grant(grant_id),
 post_crisis_event_id uuid REFERENCES care.post_crisis_event(id), due_at timestamptz, expires_at timestamptz,
 revision bigint NOT NULL CHECK(revision>0), state text NOT NULL CHECK(state IN
 ('anchor_pending','scheduled','claimed','authorized','sent','cancelled','expired','unknown','reconciliation_needed')),
 inbox_message_id uuid UNIQUE, effect_key uuid NOT NULL UNIQUE, fence bigint NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL, cancel_requested boolean NOT NULL DEFAULT false,
 CHECK((post_crisis_event_id IS NULL)=(due_at IS NULL)),
 CHECK((due_at IS NULL)=(expires_at IS NULL)), CHECK(due_at<=expires_at)
);
CREATE INDEX follow_up_due ON care.follow_up(state,due_at);
CREATE TABLE care.inbox_message (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id),
 subject_id uuid NOT NULL, recipient_account_id uuid NOT NULL,
 followup_id uuid NOT NULL UNIQUE REFERENCES care.follow_up(id), effect_key uuid NOT NULL UNIQUE,
 text_ciphertext text NOT NULL, sources jsonb NOT NULL, created_at timestamptz NOT NULL,
 expires_at timestamptz NOT NULL, read_at timestamptz
);
CREATE TABLE care.outcome (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES core.session(id), subject_id uuid NOT NULL,
 actor_id uuid NOT NULL, pathway_id uuid, state text NOT NULL CHECK(state IN
 ('offered','chosen','declined','attempted','received','accepted','connected','reported_benefit','unknown')),
 carer_support boolean NOT NULL, source jsonb, observed_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL, revision bigint NOT NULL CHECK(revision>0)
);
CREATE TABLE lifecycle.hold (
 id uuid PRIMARY KEY, revision bigint NOT NULL CHECK(revision>0), scope jsonb NOT NULL,
 reason text NOT NULL, authority_ref uuid NOT NULL, actor_id uuid NOT NULL,
 created_at timestamptz NOT NULL, expires_at timestamptz, released_at timestamptz,
 CHECK(expires_at IS NULL OR expires_at>created_at)
);
CREATE TABLE rights.request (
 id uuid PRIMARY KEY, subject_id uuid NOT NULL, requester_id uuid NOT NULL,
 session_id uuid NOT NULL REFERENCES core.session(id), kind text NOT NULL CHECK(kind IN ('export','delete')),
 ceremony_id uuid NOT NULL UNIQUE, revision bigint NOT NULL CHECK(revision>0),
 state text NOT NULL CHECK(state IN ('requested','eligible','held','active_purged','backup_pending',
 'completed','completed_with_exceptions','reconciliation_needed','failed')),
 requested_at timestamptz NOT NULL, deadline timestamptz NOT NULL,
 exceptions text[] NOT NULL, download_id uuid, export_ciphertext text, export_expires_at timestamptz,
 downloaded_at timestamptz
);
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_purpose_check;
ALTER TABLE lifecycle.copy ADD CHECK(purpose IN ('support','plan','referral','follow_up','rights'));
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_aggregate_type_check;
ALTER TABLE lifecycle.copy ADD CHECK(aggregate_type IN
 ('session','turn','message','assertion','plan','plan_field','referral','assistance_task','assistance_draft','assistance_observation','review_draft','review_intent','followup','inbox','outcome','export'));
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_anchor_kind_check;
ALTER TABLE lifecycle.copy ADD CHECK(anchor_kind IN ('last_parent_closed','plan_retired','referral_terminal_parent','capture'));
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_check1;
ALTER TABLE lifecycle.copy ADD CHECK(expires_at IS NULL OR expires_at>anchor_at);
ALTER TABLE lifecycle.copy DROP CONSTRAINT copy_check;
ALTER TABLE lifecycle.copy ADD CHECK(state='purged' OR (state='anchor_pending')=(anchor_at IS NULL AND expires_at IS NULL));
ALTER TABLE durable.duty_operation DROP CONSTRAINT duty_operation_action_check;
ALTER TABLE durable.duty_operation ADD CHECK(action IN ('identity_revoke','job_execute','lifecycle_due'));
-- Metadata discovery remains internal; human fields are filtered by guarded projections.
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['care.post_crisis_event','care.follow_up','care.inbox_message','care.outcome','rights.request'] LOOP
  EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY imp07_metadata ON %s FOR SELECT TO care_link_data_runtime USING(true)',t);
  EXECUTE format('CREATE POLICY imp07_write ON %s TO care_link_data_runtime USING(session_id::text=current_setting(''care_link.session'',true)) WITH CHECK(session_id::text=current_setting(''care_link.session'',true))',t);
  EXECUTE format('CREATE POLICY imp07_backup ON %s FOR SELECT TO care_link_backup USING(true)',t);
 END LOOP;
END $$;
GRANT SELECT,INSERT ON care.post_crisis_event,care.outcome TO care_link_data_runtime;
GRANT SELECT,INSERT,UPDATE ON care.follow_up,care.inbox_message,rights.request,lifecycle.hold TO care_link_data_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA care,rights TO care_link_backup;
GRANT SELECT ON lifecycle.hold TO care_link_backup;
-- Purge is minimization of registered active content, never a physical-erasure claim.
-- Existing append-only source rows retain references with erased ciphertext.
CREATE FUNCTION lifecycle.purge_copy(p_copy uuid,p_erased text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,lifecycle,core,plans,care,rights AS $$
DECLARE c lifecycle.copy%ROWTYPE;
BEGIN
 SELECT * INTO STRICT c FROM lifecycle.copy WHERE copy_id=p_copy FOR UPDATE;
 IF c.session_id::text IS DISTINCT FROM current_setting('care_link.session',true) THEN RAISE EXCEPTION 'copy scope'; END IF;
 IF c.state='purged' THEN RETURN; END IF;
 IF EXISTS(SELECT 1 FROM lifecycle.hold h WHERE h.released_at IS NULL
   AND (h.expires_at IS NULL OR h.expires_at>clock_timestamp())
   AND (h.scope->>'subject_id' IS NULL OR h.scope->>'subject_id'=c.subject_id::text)
   AND (h.scope->>'session_id' IS NULL OR h.scope->>'session_id'=c.session_id::text)) THEN
   RAISE EXCEPTION 'copy held'; END IF;
 IF NOT EXISTS(SELECT 1 FROM core.subject_guard s JOIN rights.request r ON r.subject_id=s.subject_id WHERE s.subject_id=c.subject_id AND s.delete_state='restricted' AND r.kind='delete')
 AND (c.anchor_at IS NULL OR c.expires_at IS NULL OR c.expires_at>clock_timestamp()) THEN
   RAISE EXCEPTION 'copy not due'; END IF;
 IF EXISTS(SELECT 1 FROM lifecycle.dependency d JOIN lifecycle.copy child ON child.copy_id=d.child_copy_id
   WHERE d.parent_copy_id=p_copy AND child.state<>'purged') THEN RAISE EXCEPTION 'dependent retained'; END IF;
 IF EXISTS(SELECT 1 FROM lifecycle.dependency d JOIN lifecycle.copy parent ON parent.copy_id=d.parent_copy_id
   WHERE d.child_copy_id=p_copy AND parent.anchor_at IS NULL AND NOT EXISTS
   (SELECT 1 FROM core.subject_guard s WHERE s.subject_id=c.subject_id AND s.delete_state='restricted')) THEN
   RAISE EXCEPTION 'parent anchor pending'; END IF;
 IF EXISTS(WITH RECURSIVE chain(id,seen,cycle) AS (
   SELECT child_copy_id,ARRAY[p_copy,child_copy_id],child_copy_id=p_copy FROM lifecycle.dependency WHERE parent_copy_id=p_copy
   UNION ALL SELECT d.child_copy_id,seen||d.child_copy_id,d.child_copy_id=ANY(seen)
   FROM chain JOIN lifecycle.dependency d ON d.parent_copy_id=chain.id WHERE NOT cycle
 ) SELECT 1 FROM chain WHERE cycle) THEN RAISE EXCEPTION 'copy cycle'; END IF;
 IF EXISTS(SELECT 1 FROM lifecycle.copy_source(p_copy) WHERE blocked_reason IS NOT NULL) THEN
   RAISE EXCEPTION 'source dependency unresolved'; END IF;
 IF EXISTS(SELECT 1 FROM core.subject_guard s JOIN rights.request r ON r.subject_id=s.subject_id
   CROSS JOIN lifecycle.copy_source(p_copy) src
   WHERE s.subject_id=c.subject_id AND s.delete_state='restricted'
   AND r.kind='delete' AND r.requester_id<>src.owner_id) THEN RAISE EXCEPTION 'other author retained'; END IF;
 IF c.aggregate_type='turn' THEN UPDATE core.turn SET text_ciphertext=p_erased WHERE id=c.aggregate_id AND session_id=c.session_id;
 ELSIF c.aggregate_type='message' THEN UPDATE core.message SET text_ciphertext=p_erased WHERE id=c.aggregate_id AND session_id=c.session_id;
 ELSIF c.aggregate_type='assertion' THEN UPDATE core.assertion SET value_ciphertext=p_erased WHERE id=c.aggregate_id AND session_id=c.session_id;
 ELSIF c.aggregate_type='plan_field' THEN UPDATE plans.field SET value_ciphertext=p_erased,source=NULL WHERE id=c.aggregate_id AND session_id=c.session_id;
 ELSIF c.aggregate_type IN ('referral','assistance_task','assistance_draft','assistance_observation') THEN
  IF EXISTS(SELECT 1 FROM lifecycle.copy_source(p_copy) WHERE blocked_reason IS NOT NULL) THEN
   RAISE EXCEPTION 'source dependency unresolved'; END IF;
  IF EXISTS(SELECT 1 FROM core.subject_guard s JOIN rights.request r ON r.subject_id=s.subject_id
    CROSS JOIN lifecycle.copy_source(p_copy) src
    WHERE s.subject_id=c.subject_id AND s.delete_state='restricted'
    AND r.kind='delete' AND r.requester_id<>src.owner_id) THEN RAISE EXCEPTION 'other author retained'; END IF;
  CASE c.aggregate_type
   WHEN 'referral' THEN UPDATE referral.generation SET payload_ciphertext=p_erased,selected='[]'::jsonb,state='purged' WHERE id=c.aggregate_id AND session_id=c.session_id;
   WHEN 'assistance_task' THEN UPDATE assistance.task SET body=jsonb_build_object('ciphertext',p_erased) WHERE id=c.aggregate_id AND session_id=c.session_id;
   WHEN 'assistance_draft' THEN UPDATE assistance.draft SET body=jsonb_build_object('ciphertext',p_erased) WHERE id=c.aggregate_id AND session_id=c.session_id;
   WHEN 'assistance_observation' THEN UPDATE assistance.invocation SET body=jsonb_build_object('ciphertext',p_erased) WHERE id=c.aggregate_id AND session_id=c.session_id;
  END CASE;
  IF c.aggregate_type<>'referral' THEN
   UPDATE assistance.operation SET response_ciphertext=p_erased
    WHERE session_id=c.session_id AND (resource_id=c.aggregate_id OR
     (action='task_create' AND principal_id=(SELECT owner_id FROM lifecycle.copy_source(p_copy))));
  END IF;
 ELSIF c.aggregate_type='review_draft' THEN DELETE FROM core.review_draft WHERE id=c.aggregate_id AND session_id=c.session_id;
 ELSIF c.aggregate_type='review_intent' THEN DELETE FROM core.review_intent WHERE operation_id=c.aggregate_id AND session_id=c.session_id;
 ELSIF c.aggregate_type='inbox' THEN UPDATE care.inbox_message SET text_ciphertext=p_erased,sources='[]'::jsonb WHERE id=c.aggregate_id AND session_id=c.session_id;
 ELSIF c.aggregate_type='export' THEN UPDATE rights.request SET export_ciphertext=NULL WHERE id=c.aggregate_id AND session_id=c.session_id;
 ELSIF c.aggregate_type NOT IN ('session','plan','followup','outcome') THEN RAISE EXCEPTION 'unknown copy type';
 END IF;
 UPDATE lifecycle.copy SET state='purged' WHERE copy_id=p_copy;
END $$;
REVOKE ALL ON FUNCTION lifecycle.purge_copy(uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lifecycle.purge_copy(uuid,text) TO care_link_data_runtime;

-- Source metadata only: workload cleanup never receives a content projection.
CREATE FUNCTION lifecycle.copy_source(p_copy uuid) RETURNS TABLE(owner_id uuid,blocked_reason text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,lifecycle,core,plans,referral,assistance,care AS $$
DECLARE c lifecycle.copy%ROWTYPE; task uuid; anchor timestamptz; expiry timestamptz; accelerated boolean;
BEGIN
 SELECT * INTO STRICT c FROM lifecycle.copy WHERE copy_id=p_copy;
 IF c.session_id::text IS DISTINCT FROM current_setting('care_link.session',true) THEN RAISE EXCEPTION 'copy scope'; END IF;
 blocked_reason:=NULL;
 IF NOT EXISTS(SELECT 1 FROM core.session WHERE id=c.session_id AND persona_id=c.subject_id) THEN
  blocked_reason:='source_inventory_review_required'; RETURN NEXT; RETURN;
 END IF;
 CASE c.aggregate_type
 WHEN 'referral' THEN
  SELECT author_id INTO owner_id FROM referral.generation WHERE id=c.aggregate_id AND session_id=c.session_id AND subject_id=c.subject_id;
  IF EXISTS(SELECT 1 FROM referral.dispatch WHERE referral_id=c.aggregate_id AND session_id=c.session_id
    AND state NOT IN ('received','accepted','rejected','cancelled')) THEN
   blocked_reason:='delivery_reconciliation_required';
  END IF;
 WHEN 'assistance_task' THEN
  SELECT principal_id,id INTO owner_id,task FROM assistance.task WHERE id=c.aggregate_id AND session_id=c.session_id;
 WHEN 'assistance_draft' THEN
  SELECT principal_id,task_id INTO owner_id,task FROM assistance.draft WHERE id=c.aggregate_id AND session_id=c.session_id;
 WHEN 'assistance_observation' THEN
  SELECT principal_id,task_id INTO owner_id,task FROM assistance.invocation WHERE id=c.aggregate_id AND session_id=c.session_id;
 WHEN 'review_draft' THEN SELECT principal_id INTO owner_id FROM core.review_draft WHERE id=c.aggregate_id AND session_id=c.session_id;
 WHEN 'review_intent' THEN SELECT principal_id INTO owner_id FROM core.review_intent WHERE operation_id=c.aggregate_id AND session_id=c.session_id;
 WHEN 'turn' THEN SELECT author_id INTO owner_id FROM core.turn WHERE id=c.aggregate_id AND session_id=c.session_id;
 WHEN 'message' THEN SELECT sender_id INTO owner_id FROM core.message WHERE id=c.aggregate_id AND session_id=c.session_id;
 WHEN 'assertion' THEN SELECT author_id INTO owner_id FROM core.assertion WHERE id=c.aggregate_id AND session_id=c.session_id AND subject_id=c.subject_id;
 WHEN 'plan_field' THEN SELECT author_id INTO owner_id FROM plans.field WHERE id=c.aggregate_id AND session_id=c.session_id AND subject_id=c.subject_id;
 WHEN 'outcome' THEN SELECT actor_id INTO owner_id FROM care.outcome WHERE id=c.aggregate_id AND session_id=c.session_id AND subject_id=c.subject_id;
 WHEN 'inbox' THEN SELECT recipient_account_id INTO owner_id FROM care.inbox_message WHERE id=c.aggregate_id AND session_id=c.session_id AND subject_id=c.subject_id;
 WHEN 'followup' THEN SELECT recipient_account_id INTO owner_id FROM care.follow_up WHERE id=c.aggregate_id AND session_id=c.session_id AND subject_id=c.subject_id;
 WHEN 'session' THEN SELECT participant_account_id INTO owner_id FROM core.session WHERE id=c.aggregate_id AND id=c.session_id AND persona_id=c.subject_id;
 WHEN 'plan' THEN SELECT p.account_id INTO owner_id FROM plans.plan a JOIN core.persona p ON p.id=a.subject_id WHERE a.id=c.aggregate_id AND a.session_id=c.session_id AND a.subject_id=c.subject_id;
 WHEN 'export' THEN SELECT requester_id INTO owner_id FROM rights.request WHERE id=c.aggregate_id AND session_id=c.session_id AND subject_id=c.subject_id;
 ELSE blocked_reason:='source_inventory_review_required';
 END CASE;
 IF owner_id IS NULL THEN blocked_reason:='source_inventory_review_required'; RETURN NEXT; RETURN; END IF;
 SELECT EXISTS(SELECT 1 FROM core.subject_guard s JOIN rights.request r ON r.subject_id=s.subject_id
   WHERE s.subject_id=c.subject_id AND s.delete_state='restricted' AND r.kind='delete') INTO accelerated;
 IF NOT accelerated THEN
  CASE c.anchor_kind
   WHEN 'last_parent_closed' THEN
    SELECT closed_at INTO anchor FROM core.session WHERE id=c.session_id;
    IF anchor IS NULL THEN blocked_reason:='anchor_pending';
    ELSIF c.anchor_at IS DISTINCT FROM anchor OR c.expires_at IS DISTINCT FROM anchor+interval '7 days' THEN
     blocked_reason:='source_anchor_mismatch'; END IF;
   WHEN 'plan_retired' THEN
    IF c.aggregate_type='plan' THEN SELECT retired_at INTO anchor FROM plans.plan WHERE id=c.aggregate_id;
    ELSE SELECT p.retired_at INTO anchor FROM plans.field f JOIN plans.plan p ON p.id=f.plan_id WHERE f.id=c.aggregate_id; END IF;
    IF anchor IS NULL THEN blocked_reason:='anchor_pending';
    ELSIF c.anchor_at IS DISTINCT FROM anchor OR c.expires_at IS DISTINCT FROM anchor+interval '30 days' THEN
     blocked_reason:='source_anchor_mismatch'; END IF;
   WHEN 'referral_terminal_parent' THEN
    SELECT closed_at INTO anchor FROM core.session WHERE id=c.session_id;
    IF anchor IS NULL OR c.anchor_at IS NULL THEN blocked_reason:='anchor_pending';
    ELSIF c.anchor_at<anchor OR c.expires_at IS DISTINCT FROM c.anchor_at+interval '7 days' THEN
     blocked_reason:='source_anchor_mismatch'; END IF;
   WHEN 'capture' THEN
    IF c.aggregate_type='export' THEN SELECT export_expires_at INTO expiry FROM rights.request WHERE id=c.aggregate_id;
    ELSIF c.aggregate_type='inbox' THEN SELECT expires_at INTO expiry FROM care.inbox_message WHERE id=c.aggregate_id;
    ELSIF c.aggregate_type='review_draft' THEN SELECT expires_at INTO expiry FROM core.review_draft WHERE id=c.aggregate_id;
    ELSIF c.aggregate_type='review_intent' THEN SELECT created_at+interval '1 day' INTO expiry FROM core.review_intent WHERE operation_id=c.aggregate_id; END IF;
    IF expiry IS NULL OR c.expires_at IS DISTINCT FROM expiry THEN blocked_reason:='source_anchor_mismatch'; END IF;
   ELSE blocked_reason:='source_anchor_mismatch';
  END CASE;
 END IF;
 IF task IS NOT NULL AND EXISTS(SELECT 1 FROM assistance.inference_job WHERE task_id=task
   AND state IN ('running','compute_unknown')) THEN blocked_reason:='compute_reconciliation_required'; END IF;
 RETURN NEXT;
END $$;
REVOKE ALL ON FUNCTION lifecycle.copy_source(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lifecycle.copy_source(uuid) TO care_link_data_runtime;

-- The sole lifecycle eraser invokes this narrowly scoped function as migration
-- owner. Ordinary gateway updates cannot alter immutable referral generations.
CREATE OR REPLACE FUNCTION referral.immutable_generation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF current_user=(SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='referral.generation'::regclass)
 AND NEW.state='purged' THEN RETURN NEW; END IF;
 IF (to_jsonb(OLD)-'revision'-'state'-'consent_id'-'review_id'-'dispatch_id') IS DISTINCT FROM
 (to_jsonb(NEW)-'revision'-'state'-'consent_id'-'review_id'-'dispatch_id') THEN
 RAISE EXCEPTION 'referral payload generations are immutable'; END IF;
 RETURN NEW;
END $$;

-- Bounded scans rotate even when a candidate is held or requires reconciliation.
CREATE TABLE lifecycle.scan_cursor(class text PRIMARY KEY, subject_id uuid NOT NULL);
GRANT SELECT,INSERT,UPDATE ON lifecycle.scan_cursor TO care_link_data_runtime;
GRANT SELECT ON lifecycle.scan_cursor TO care_link_backup;

-- Existing optional review recovery content becomes explicit captured-purpose
-- inventory. No account/linkage schedule is borrowed from these synthetic copies.
DO $$ BEGIN
 IF to_regclass('core.review_draft') IS NOT NULL THEN
  EXECUTE $backfill$INSERT INTO lifecycle.copy
   SELECT gen_random_uuid(),s.persona_id,d.session_id,'support','review_draft',d.id,
    'postgres:review_draft:'||d.id,'synthetic_content',
    COALESCE((SELECT encryption_key_ref FROM lifecycle.copy c WHERE c.session_id=s.id LIMIT 1),'unavailable'),
    'capture',d.updated_at,d.expires_at,'retained',d.updated_at
   FROM core.review_draft d JOIN core.session s ON s.id=d.session_id
   WHERE NOT EXISTS(SELECT 1 FROM lifecycle.copy c WHERE c.aggregate_type='review_draft' AND c.aggregate_id=d.id)$backfill$;
  EXECUTE $backfill$INSERT INTO lifecycle.copy
   SELECT gen_random_uuid(),s.persona_id,i.session_id,'support','review_intent',i.operation_id,
    'postgres:review_intent:'||i.operation_id,'synthetic_content',
    COALESCE((SELECT encryption_key_ref FROM lifecycle.copy c WHERE c.session_id=s.id LIMIT 1),'unavailable'),
    'capture',i.created_at,i.created_at+interval '1 day','retained',i.created_at
   FROM core.review_intent i JOIN core.session s ON s.id=i.session_id
   WHERE NOT EXISTS(SELECT 1 FROM lifecycle.copy c WHERE c.aggregate_type='review_intent' AND c.aggregate_id=i.operation_id)$backfill$;
 END IF;
END $$;
