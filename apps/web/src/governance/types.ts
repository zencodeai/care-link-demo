export type Locale = "en-CA" | "fr-CA";
export interface Artifact {
  digest: string;
  kind: string;
  version: string;
  state: "registered" | "review_pending" | "approved" | "rejected" | "retired";
}
export interface Activation {
  id: string;
  epoch: string;
  bundle_digest: string;
  state: "proposed" | "staged" | "ready" | "active" | "rejected" | "superseded";
  missing_instances: string[];
  revision: string;
}
export interface Incident {
  id: string;
  revision: string;
  state: "open" | "contained" | "reviewing" | "remediated" | "closed";
  kind: string;
  review_due_at: string;
}
export interface Health {
  capability: string;
  ready: boolean;
  reasons: string[];
  epoch: string;
  serving_generation: string;
}
export interface Receipt {
  operation_id: string;
  state: string;
  resource_id: string | null;
  revision: string;
  audit_ref: string;
}
export interface Audit {
  id: string;
  sequence: string;
  operation_id: string | null;
  action: string;
  decision: string;
  input_digest: string;
  output_digest: string;
  previous_hash: string;
  hash: string;
  created_at: string;
}
export interface AuditPage {
  items: Audit[];
  next_cursor: string | null;
}
export interface Count {
  numerator: number;
  denominator: number;
  unknown: number;
}
export type Metrics =
  | {
      definition_version: string;
      cohort_size: null;
      suppressed: true;
      safety: null;
      access: null;
      equity: null;
      police_avoidance: null;
      exposure_aggregate: null;
    }
  | {
      definition_version: string;
      cohort_size: number;
      suppressed: false;
      safety: Count;
      access: Count;
      equity: Count;
      police_avoidance: Count;
      exposure_aggregate: Count | null;
    };
export interface ArtifactContext {
  artifact: Artifact;
  source_revision: string;
  change_class: string;
  governed_domains: string[];
  changed_paths: string[];
  required_authorities: string[];
  missing_authorities: string[];
  evidence_digests: string[];
  previous_digest: string | null;
  payload_digest: string;
}
export interface Responses {
  GovernanceArtifactContext: ArtifactContext;
  ArtifactView: Artifact;
  ActivationView: Activation;
  IncidentView: Incident;
  HealthView: Health;
  CommandResult: Receipt;
  AuditPage: AuditPage;
  MetricsView: Metrics;
}
export type Output = keyof Responses;
export interface Command<K extends Output = Output> {
  path: string;
  input: string;
  output: K;
  body: unknown;
  key: string;
}
