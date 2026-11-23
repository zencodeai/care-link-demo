-- Replay persistence holds only bounded synthetic evidence references and pins.
-- Corpus intake and its shorter remaining retention are checked by the evaluator.
CREATE TABLE quality.evaluation (
 id uuid PRIMARY KEY,
 principal_id uuid NOT NULL REFERENCES control.principal_guard(principal_id) ON DELETE CASCADE,
 scenario_id uuid NOT NULL,
 input_manifest_digest text NOT NULL CHECK(input_manifest_digest~'^[0-9a-f]{64}$'),
 recorded_outputs_digest text NOT NULL CHECK(recorded_outputs_digest~'^[0-9a-f]{64}$'),
 bundle_digest text NOT NULL CHECK(bundle_digest~'^[0-9a-f]{64}$'),
 state text NOT NULL CHECK(state IN ('completed','failed')),
 evidence_digest text CHECK(evidence_digest~'^[0-9a-f]{64}$'),
 created_at timestamptz NOT NULL,
 expires_at timestamptz NOT NULL,
 CHECK(state='failed' OR evidence_digest IS NOT NULL),
 CHECK(expires_at>created_at AND expires_at<=created_at+interval '168 hours')
);
CREATE INDEX evaluation_expiry ON quality.evaluation(expires_at);
REVOKE ALL ON quality.evaluation FROM PUBLIC;
GRANT SELECT,INSERT ON quality.evaluation TO care_link_data_runtime;
GRANT SELECT ON quality.evaluation TO care_link_backup;
ALTER TABLE quality.evaluation ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality.evaluation FORCE ROW LEVEL SECURITY;
CREATE POLICY evaluation_read ON quality.evaluation FOR SELECT TO care_link_data_runtime
 USING(expires_at>clock_timestamp() AND EXISTS (
  SELECT 1 FROM control.principal_guard p
   WHERE p.principal_id::text=current_setting('care_link.principal',true)
    AND NOT p.revoked AND p.role IN ('trainer','governance')
 ));
CREATE POLICY evaluation_write ON quality.evaluation FOR INSERT TO care_link_data_runtime
 WITH CHECK(principal_id::text=current_setting('care_link.principal',true) AND EXISTS (
  SELECT 1 FROM control.principal_guard p
   WHERE p.principal_id=quality.evaluation.principal_id
    AND NOT p.revoked AND p.role IN ('trainer','governance')
 ));
CREATE POLICY evaluation_backup ON quality.evaluation FOR SELECT TO care_link_backup USING(true);
