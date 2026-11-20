import type {
  AssertionValue,
  Source,
  Consent,
  DirectoryEntry,
} from "../plans/api";
export type { Consent, DirectoryEntry };
export interface Selection {
  field: string;
  source: Source;
}
export interface Payload {
  session_id: string;
  subject_id: string;
  recipient_service_id: string;
  purpose: "referral";
  fields: { field: string; value: AssertionValue; sources: Source[] }[];
  qualifications: string[];
}
export interface Referral {
  id: string;
  revision: string;
  generation: string;
  payload: Payload;
  digest: string;
  state: string;
  consent_id: string | null;
  review_id: string | null;
  dispatch_id: string | null;
}
export interface Review {
  id: string;
  draft_id: string;
  decision: "accept" | "edit" | "reject";
  reviewer_id: string;
  exact_digest: string;
  expires_at: string;
  revision: string;
}
export interface Context {
  referral: Referral;
  versions: Record<string, string>;
  review: Review | null;
  consent_expires_at: string | null;
}
export interface Dispatch {
  dispatch_id: string;
  referral_id: string;
  revision: string;
  state:
    | "pending"
    | "authorized"
    | "attempted"
    | "unknown"
    | "received"
    | "partial"
    | "accepted"
    | "rejected"
    | "cancelled"
    | "reconciliation_needed";
  attempt_count: number;
  receipt_id: string | null;
}
export interface Receipt {
  id: string;
  dispatch_id: string;
  recipient_service_id: string;
  payload_digest: string;
  status:
    | "received"
    | "accepted"
    | "partial"
    | "rejected"
    | "clarification_requested"
    | "unavailable"
    | "not_found";
  accepted_fields: string[];
  observed_at: string;
}
export interface ReceiverDetail {
  payload: Payload;
  revision: string;
  receipt: Receipt;
}
export interface Inbox {
  dispatch_ids: string[];
  next_cursor: string | null;
}
export interface Conversation {
  id: string;
  revision: string;
  subject_id: string | null;
}
