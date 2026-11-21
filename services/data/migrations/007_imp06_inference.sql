-- Durable compute occupancy has no payload/transcript content. Only the data
-- gateway runtime receives grants. Provisioning seeds the fixed two slots.
CREATE SCHEMA IF NOT EXISTS assistance;
REVOKE ALL ON SCHEMA assistance FROM PUBLIC;
GRANT USAGE ON SCHEMA assistance TO care_link_data_runtime,care_link_backup;
CREATE TABLE assistance.compute_slot (
 id text PRIMARY KEY CHECK (id IN ('local-1','local-2')),
 state text NOT NULL CHECK(state IN ('free','occupied','compute_unknown')),
 job_id uuid UNIQUE,
 bridge_generation text
);
INSERT INTO assistance.compute_slot(id,state) VALUES ('local-1','free'),('local-2','free');
CREATE TABLE assistance.inference_job (
 id uuid PRIMARY KEY,
 task_id uuid NOT NULL,
 step_id uuid NOT NULL,
 fence bigint NOT NULL CHECK(fence>=0),
 revision bigint NOT NULL CHECK(revision>=0),
 model_digest text NOT NULL CHECK(model_digest ~ '^[0-9a-f]{64}$'),
 prompt_digest text NOT NULL CHECK(prompt_digest ~ '^[0-9a-f]{64}$'),
 request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
 result_digest text CHECK(result_digest ~ '^[0-9a-f]{64}$'),
 state text NOT NULL CHECK(state IN ('running','compute_unknown','completed','fenced','stopped')),
 deadline timestamptz NOT NULL,
 slot_id text NOT NULL REFERENCES assistance.compute_slot(id),
 bridge_generation text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(task_id,step_id,fence)
);
ALTER TABLE assistance.compute_slot ADD FOREIGN KEY(job_id) REFERENCES assistance.inference_job(id);
GRANT SELECT,INSERT,UPDATE ON assistance.inference_job TO care_link_data_runtime;
GRANT SELECT,UPDATE ON assistance.compute_slot TO care_link_data_runtime;
GRANT SELECT ON assistance.inference_job,assistance.compute_slot TO care_link_backup;
ALTER TABLE assistance.inference_job ENABLE ROW LEVEL SECURITY;
ALTER TABLE assistance.inference_job FORCE ROW LEVEL SECURITY;
ALTER TABLE assistance.compute_slot ENABLE ROW LEVEL SECURITY;
ALTER TABLE assistance.compute_slot FORCE ROW LEVEL SECURITY;
CREATE POLICY data_jobs ON assistance.inference_job TO care_link_data_runtime USING(true) WITH CHECK(true);
CREATE POLICY data_slots ON assistance.compute_slot TO care_link_data_runtime USING(true) WITH CHECK(true);
CREATE POLICY backup_jobs ON assistance.inference_job FOR SELECT TO care_link_backup USING(true);
CREATE POLICY backup_slots ON assistance.compute_slot FOR SELECT TO care_link_backup USING(true);
