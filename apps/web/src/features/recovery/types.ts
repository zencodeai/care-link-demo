export type Locale = "en-CA" | "fr-CA";
export interface Head {
  journal_id: string;
  generation: string;
  tip: string;
  tip_digest: string;
  restriction_barrier: string;
  signature: string;
  observed_at: string;
}
export interface Backup {
  id: string;
  manifest_digest: string;
  capture_at: string;
  expires_at: string;
  schema_version: string;
  journal_barrier: string;
  audit_digest: string;
  state: "capturing" | "verified" | "failed" | "expired";
}
export interface Target {
  id: string;
  revision: string;
  backup_id: string;
  state:
    | "requested"
    | "restoring"
    | "quarantined"
    | "reconciling"
    | "validated"
    | "promotion_pending"
    | "fenced"
    | "serving"
    | "failed";
  head: Head;
  validation_digest: string | null;
  serving_generation: string;
}
export interface Binding {
  target_id: string;
  backup_digest: string;
  schema_digest: string;
  artifact_digest: string;
  journal_id: string;
  journal_generation: string;
  head_digest: string;
  restriction_barrier: string;
  validation_digest: string;
  serving_generation: string;
}
export interface Promotion {
  id: string;
  revision: string;
  target_id: string;
  binding_digest: string;
  state:
    | "proposed"
    | "approved"
    | "maintenance"
    | "fenced_old"
    | "routed_target"
    | "enabled_target"
    | "smoke_verified"
    | "invalidated";
  approval_id: string | null;
  expires_at: string | null;
}
export interface Receipt {
  operation_id: string;
  state: "committed" | "pending" | "unknown" | "rejected";
  resource_id: string | null;
  revision: string;
  audit_ref: string;
}
export interface Responses {
  BackupView: Backup;
  RestoreView: Target;
  PromotionView: Promotion;
  PromotionBinding: Binding;
  CommandResult: Receipt;
}
export type Output = keyof Responses;
export interface Command<K extends Output = Output> {
  path: string;
  input: string;
  output: K;
  body: unknown;
  key: string;
}
export interface TargetEvidence {
  target: Target;
  binding: Binding | null;
}
export interface ProposalEvidence {
  promotion: Promotion;
  binding: Binding;
}
