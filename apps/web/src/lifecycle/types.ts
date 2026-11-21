import type { Assertion, Plan } from "../plans/api";
export type Locale = "en-CA" | "fr-CA";
export interface SessionContext {
  id: string;
  revision: string;
  subject_id: string | null;
  subject_revision?: string;
}
export interface Anchor {
  id: string;
  session_id: string;
  occurred_at: string;
  revision: string;
}
export interface FollowUp {
  id: string;
  session_id: string;
  revision: string;
  state:
    | "anchor_pending"
    | "scheduled"
    | "claimed"
    | "authorized"
    | "sent"
    | "cancelled"
    | "expired"
    | "unknown"
    | "reconciliation_needed";
  due_at: string | null;
  inbox_message_id: string | null;
}
export interface InboxMessage {
  id: string;
  recipient_account_id: string;
  followup_id: string;
  source_session_id: string;
  text: string;
  created_at: string;
  read_at: string | null;
  expires_at: string;
}
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}
export interface Outcome {
  id: string;
  revision: string;
  session_id: string;
  state:
    | "offered"
    | "chosen"
    | "declined"
    | "attempted"
    | "received"
    | "accepted"
    | "connected"
    | "reported_benefit"
    | "unknown";
  carer_support: boolean;
  observed_at: string;
}
export interface Rights {
  id: string;
  revision: string;
  kind: "export" | "delete";
  state:
    | "requested"
    | "eligible"
    | "held"
    | "active_purged"
    | "backup_pending"
    | "completed"
    | "completed_with_exceptions"
    | "reconciliation_needed"
    | "failed";
  exceptions: string[];
  download_id: string | null;
  deadline: string;
}
export interface Export {
  export_id: string;
  subject_id: string;
  created_at: string;
  assertions: Assertion[];
  plans: Plan[];
  outcome_refs: string[];
  exceptions: string[];
}
