-- Run in a distinct receiver database by separate migration authority.
-- Never grant the business gateway runtime access to this schema or credentials.
CREATE SCHEMA receiver;
REVOKE ALL ON SCHEMA receiver FROM PUBLIC;
CREATE ROLE care_link_receiver_runtime NOLOGIN;
GRANT USAGE ON SCHEMA receiver TO care_link_receiver_runtime;
CREATE TABLE receiver.package (
 recipient_service_id uuid NOT NULL, dispatch_id uuid NOT NULL,
 payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),
 payload_ciphertext text NOT NULL, authorization_id uuid NOT NULL,
 revision bigint NOT NULL DEFAULT 1, receipt jsonb NOT NULL,
 PRIMARY KEY(recipient_service_id,dispatch_id)
);
CREATE TABLE receiver.decision (
 operation_id uuid PRIMARY KEY, principal_id uuid NOT NULL, recipient_service_id uuid NOT NULL,
 dispatch_id uuid NOT NULL, request_digest text NOT NULL, receipt jsonb NOT NULL,
 created_at timestamptz NOT NULL
);
GRANT SELECT,INSERT,UPDATE ON receiver.package TO care_link_receiver_runtime;
GRANT SELECT,INSERT ON receiver.decision TO care_link_receiver_runtime;
CREATE FUNCTION receiver.immutable_package() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.revision<>OLD.revision+1 OR
 (to_jsonb(OLD)-'revision'-'receipt') IS DISTINCT FROM (to_jsonb(NEW)-'revision'-'receipt') THEN
 RAISE EXCEPTION 'receiver package identity and content are immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_package BEFORE UPDATE ON receiver.package
 FOR EACH ROW EXECUTE FUNCTION receiver.immutable_package();
CREATE TABLE receiver.copy (
 recipient_service_id uuid NOT NULL, dispatch_id uuid NOT NULL,
 subject_id uuid NOT NULL, session_id uuid NOT NULL,
 purpose text NOT NULL CHECK(purpose='referral'), content_ref text NOT NULL,
 classification text NOT NULL CHECK(classification='synthetic_content'),
 encryption_key_ref text NOT NULL, anchor_kind text NOT NULL CHECK(anchor_kind='parent_and_delivery_terminal'),
 retention_days integer NOT NULL DEFAULT 7 CHECK(retention_days=7),
 anchor_at timestamptz, expires_at timestamptz,
 state text NOT NULL CHECK(state='anchor_pending'), created_at timestamptz NOT NULL,
 PRIMARY KEY(recipient_service_id,dispatch_id),
 FOREIGN KEY(recipient_service_id,dispatch_id) REFERENCES receiver.package(recipient_service_id,dispatch_id)
);
GRANT SELECT,INSERT ON receiver.copy TO care_link_receiver_runtime;
