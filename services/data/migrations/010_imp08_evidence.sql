-- Scoped audit metadata and pre-reviewed fixed aggregate releases. Business
-- gateway gets no general SELECT on audit.event and no aggregate provisioning.
CREATE TABLE access.audit_grant (
 id uuid PRIMARY KEY, revision bigint NOT NULL CHECK(revision>0),
 grantor_id uuid NOT NULL REFERENCES control.principal_guard(principal_id) ON DELETE CASCADE,
 grantor_human_id uuid NOT NULL, grantor_identity_revision bigint NOT NULL,
 grantor_role_revision bigint NOT NULL,
 grantee_id uuid NOT NULL REFERENCES control.principal_guard(principal_id) ON DELETE CASCADE,
 grantee_identity_revision bigint NOT NULL, grantee_role_revision bigint NOT NULL,
 control_epoch bigint NOT NULL, scope jsonb NOT NULL, request jsonb NOT NULL,
 approval_receipt_id uuid NOT NULL REFERENCES governance.approval(id),
 window_from timestamptz NOT NULL, window_to timestamptz NOT NULL,
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 revoked boolean NOT NULL DEFAULT false,
 CHECK(window_from<window_to), CHECK(expires_at>created_at),
 CHECK(expires_at<=created_at+interval '15 minutes'),
 CHECK(scope->>'purpose'='audit' AND scope->'fields'='[]'::jsonb)
);
CREATE TABLE audit.export_request (
 id uuid PRIMARY KEY, principal_id uuid NOT NULL REFERENCES control.principal_guard(principal_id) ON DELETE CASCADE,
 grant_id uuid NOT NULL REFERENCES access.audit_grant(id) ON DELETE CASCADE,
 revision bigint NOT NULL CHECK(revision>0), query jsonb NOT NULL,
 query_digest text NOT NULL CHECK(query_digest ~ '^[0-9a-f]{64}$'),
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 CHECK(expires_at>created_at AND expires_at<=created_at+interval '15 minutes')
);
CREATE SCHEMA IF NOT EXISTS quality;
CREATE TABLE quality.metric_release (
 id text PRIMARY KEY CHECK(id ~ '^[0-9a-f]{64}$'),
 definition_version text NOT NULL, period_start text NOT NULL, period_end text NOT NULL,
 cells jsonb NOT NULL, source_digest text NOT NULL CHECK(source_digest ~ '^[0-9a-f]{64}$'),
 disclosure_receipt_id uuid NOT NULL REFERENCES governance.approval(id),
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 CHECK(period_start::timestamptz<period_end::timestamptz),
 CHECK(expires_at<=period_end::timestamptz+interval '90 days')
);
REVOKE ALL ON access.audit_grant,audit.export_request,quality.metric_release FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON access.audit_grant,audit.export_request TO care_link_data_runtime;
GRANT USAGE ON SCHEMA quality TO care_link_data_runtime,care_link_backup;
GRANT SELECT ON quality.metric_release TO care_link_data_runtime,care_link_backup;
GRANT SELECT ON access.audit_grant,audit.export_request TO care_link_backup;

-- This narrow metadata projection is the only audit read privilege given to
-- the business runtime. Caller context is authenticated by gateway custody.
CREATE FUNCTION audit.scoped_page(p_grant uuid,p_from timestamptz,p_to timestamptz,
 p_action text,p_after bigint,p_limit integer)
RETURNS TABLE(id uuid,sequence bigint,operation_id uuid,action text,decision text,
 input_digest text,output_digest text,previous_hash text,hash text,created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,audit,access AS $$
DECLARE g access.audit_grant%ROWTYPE;
BEGIN
 IF p_limit<1 OR p_limit>51 OR p_after<0 THEN RAISE EXCEPTION 'invalid audit page'; END IF;
 SELECT * INTO g FROM access.audit_grant WHERE access.audit_grant.id=p_grant;
 IF NOT FOUND OR g.grantee_id::text IS DISTINCT FROM current_setting('care_link.principal',true)
 OR g.revoked OR g.expires_at<=clock_timestamp()
 OR p_from<g.window_from OR p_to>g.window_to OR p_from>=p_to
 OR p_to>clock_timestamp()
 OR NOT EXISTS(SELECT 1 FROM control.principal_guard p WHERE p.principal_id=g.grantee_id
  AND NOT p.revoked AND p.identity_revision=g.grantee_identity_revision
  AND p.role_revision=g.grantee_role_revision AND p.role='auditor')
 OR NOT EXISTS(SELECT 1 FROM control.guard c WHERE c.key='demo' AND c.epoch=g.control_epoch)
 OR NOT EXISTS(SELECT 1 FROM governance.approval a WHERE a.id=g.approval_receipt_id
  AND a.active AND a.purpose='scoped_access_grant' AND a.expires_at>clock_timestamp())
 THEN RAISE EXCEPTION 'current exact audit grant required'; END IF;
 RETURN QUERY SELECT e.event_id,e.sequence,e.operation_id,e.action,e.decision,
  e.input_digest,e.output_digest,e.previous_hash,e.hash,e.created_at
 FROM audit.event e LEFT JOIN durable.operation o ON o.operation_id=e.operation_id
 LEFT JOIN core.session s ON s.id=o.session_id
 WHERE e.created_at>=p_from AND e.created_at<p_to AND e.sequence>p_after
 AND (p_action IS NULL OR e.action=p_action)
 AND ((g.scope->>'session_id') IS NULL OR o.session_id=(g.scope->>'session_id')::uuid)
 AND ((g.scope->>'subject_id') IS NULL OR s.persona_id=(g.scope->>'subject_id')::uuid)
 ORDER BY e.sequence LIMIT p_limit;
END $$;
REVOKE ALL ON FUNCTION audit.scoped_page(uuid,timestamptz,timestamptz,text,bigint,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION audit.scoped_page(uuid,timestamptz,timestamptz,text,bigint,integer) TO care_link_data_runtime;

-- A release family has one immutable, nonoverlapping period and source. Querying
-- a newly named definition cannot obtain a slightly changed overlapping count.
CREATE FUNCTION quality.fixed_release_period() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,quality AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'metric releases are immutable'; END IF;
 -- Serialize provisioning too: concurrent independent owners cannot publish
 -- overlapping releases while both see an empty range.
 PERFORM pg_advisory_xact_lock(408010);
 IF EXISTS(SELECT 1 FROM quality.metric_release r
  WHERE tstzrange(r.period_start::timestamptz,r.period_end::timestamptz,'[)') &&
        tstzrange(NEW.period_start::timestamptz,NEW.period_end::timestamptz,'[)')) THEN
  RAISE EXCEPTION 'overlapping metric release period'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER metric_fixed_period BEFORE INSERT OR UPDATE OR DELETE ON quality.metric_release
 FOR EACH ROW EXECUTE FUNCTION quality.fixed_release_period();
REVOKE ALL ON FUNCTION quality.fixed_release_period() FROM PUBLIC;
