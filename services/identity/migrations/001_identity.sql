-- Run only against a separately provisioned identity database, as migration owner.
-- The runtime login role must not own the schema/table or possess CREATE/BYPASSRLS.
BEGIN;
CREATE SCHEMA identity;
REVOKE ALL ON SCHEMA identity FROM PUBLIC;
CREATE TABLE identity.record (
    kind text NOT NULL CHECK (kind IN ('intent','session','account','proof','ceremony','signal','head','issuer','operation')),
    record_key text NOT NULL CHECK (length(record_key) BETWEEN 1 AND 256),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY(kind,record_key)
);
REVOKE ALL ON identity.record FROM PUBLIC;
-- Provision the exact runtime role externally, then grant USAGE on schema and
-- SELECT/INSERT/UPDATE/DELETE on this table only. No business credentials here.
COMMIT;
