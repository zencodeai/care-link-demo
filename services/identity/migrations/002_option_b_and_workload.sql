-- Applies after 001_identity.sql, in the separate identity database only.
-- Runtime has no DDL privileges; execute via the explicitly authorized migrator.
BEGIN;
ALTER TABLE identity.record DROP CONSTRAINT record_kind_check;
ALTER TABLE identity.record ADD CONSTRAINT record_kind_check CHECK (kind IN (
    'intent','session','account','proof','ceremony','signal','head','issuer','operation',
    'workload_state','account_marker','retention_operation','retention_hold','retention_record','backup_capture'
));
ALTER TABLE identity.record ADD CONSTRAINT restrictive_marker_shape CHECK (
    kind NOT IN ('account_marker','workload_state') OR
    COALESCE((kind = 'account_marker' AND payload @> '{"blocked":true}'::jsonb AND
      jsonb_typeof(payload->'account_id') = 'string' AND jsonb_typeof(payload->'account_key') = 'string'),false) OR
    COALESCE((kind = 'workload_state' AND payload @> '{"blocked":true}'::jsonb AND
     jsonb_typeof(payload->'subject_id') = 'string' AND
     (payload->>'peer') ~ '^spiffe://care-link[.]demo/[a-z][a-z0-9_-]{0,31}/[a-z][a-z0-9_-]{0,63}$'),false)
);
ALTER TABLE identity.record ADD CONSTRAINT retention_operation_shape CHECK (
    kind <> 'retention_operation' OR
    COALESCE((payload->>'action' IN ('deprovision','profile_purge') AND
     payload->>'provider_state' IN ('pending','confirmed') AND payload->>'owner' = 'main' AND
     jsonb_typeof(payload->'account_id') = 'string' AND jsonb_typeof(payload->'created_at') = 'string'),false)
);
ALTER TABLE identity.record ADD CONSTRAINT retention_hold_shape CHECK (
    kind <> 'retention_hold' OR
    COALESCE((payload->>'owner' = 'main' AND jsonb_typeof(payload->'reason') = 'string' AND
     jsonb_typeof(payload->'review_date') = 'string' AND jsonb_typeof(payload->'released') = 'boolean'),false)
);
ALTER TABLE identity.record ADD CONSTRAINT retention_record_shape CHECK (
    kind <> 'retention_record' OR
    COALESCE((payload->>'record_class' IN ('security_log','minimal_audit','reviewer_evidence') AND
     payload->>'owner' = 'main' AND jsonb_typeof(payload->'event_at') = 'string' AND
     jsonb_typeof(payload->'dependencies') = 'array'),false)
);
ALTER TABLE identity.record ADD CONSTRAINT backup_capture_shape CHECK (
    kind <> 'backup_capture' OR COALESCE((payload->>'state' IN ('pending','durable','expired_unlinked') AND
      payload->>'owner' = 'main' AND jsonb_typeof(payload->'custody_id') = 'string' AND jsonb_typeof(payload->'immutable_capture_at') = 'string' AND
      jsonb_typeof(payload->'expires_at') = 'string' AND jsonb_typeof(payload->'profile_account_ids') = 'array'),false)
);
CREATE INDEX identity_account_lookup ON identity.record ((payload->>'account_id')) WHERE kind='account';
CREATE INDEX identity_retention_account ON identity.record (kind,(payload->>'account_id'))
    WHERE kind IN ('retention_hold','retention_record','retention_operation');
CREATE INDEX identity_pending_workload ON identity.record ((payload->>'state'))
    WHERE kind='operation' AND payload->>'action'='workload_restrict';
COMMIT;
