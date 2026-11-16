import type {
  Assignment,
  Conversation,
  Message,
  QueueItem,
} from "../manual/api";
export type { Assignment, Conversation, Message, QueueItem };
export type Locale = "en-CA" | "fr-CA";
export interface Context {
  enabled: boolean;
  origin: string;
  run_id: string;
  slot_id: string;
  account_id: string;
  role: string;
  run_state: string;
}
export interface ViewLease {
  view_id: string;
  state: "active" | "observer";
  revision: string;
}
export interface Draft {
  id: string;
  session_id: string;
  kind: "intake" | "message";
  revision: string;
  text: string;
  expires_at: string;
}
export interface Intent {
  operation_id: string;
  session_id: string;
  kind: "intake" | "message";
  draft_revision: string;
  state: string;
  action: "session_turns" | "message_send";
  payload: Record<string, unknown> | null;
  created_at: string;
}
export interface Handshake {
  expires_at: string;
  challenge_id: string;
  assignment_id: string;
  participant_acknowledged: boolean;
  worker_acknowledged: boolean;
  evidence_id: string | null;
  worker_ack_id: string | null;
}
export interface Workspace {
  run_id: string;
  run_state: string;
  conversations: Conversation[];
  conversation: Conversation | null;
  assignment: Assignment | null;
  drafts: Draft[];
  pending_intents: Intent[];
  handshake: Handshake | null;
  disclosure_acknowledged: boolean;
  intake_submitted: boolean;
  interrupt_expires_at: string | null;
}
