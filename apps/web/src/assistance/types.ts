import type { Source as BaseSource } from "../plans/api";
type Source = Omit<BaseSource, "verification"> & {
  verification: "unverified" | "verified" | "disputed" | "unknown";
};
export type Locale = "en-CA" | "fr-CA";
export interface Scope {
  session_id: string | null;
  subject_id: string | null;
  purpose: "support";
  fields: ("needs" | "preferences" | "observations")[];
  recipient_id: string | null;
}
export interface Task {
  id: string;
  revision: string;
  function: string;
  state: string;
  deadline: string;
  steps_used: number;
  tools_used: number;
  scope: Scope;
}
export interface Draft {
  id: string;
  revision: string;
  task_id: string | null;
  kind: string;
  text: string;
  sources: Source[];
  payload_digest: string;
  source_vector: Record<string, string>;
  state: "proposed" | "review_pending" | "accepted" | "rejected" | "stale";
}
export interface Availability {
  available: boolean;
  reason: string | null;
  functions: string[];
}
export interface TaskContext {
  task: Task;
  draft_id: string | null;
  available: boolean;
  reason: string | null;
}
export interface DraftContext {
  draft: Draft;
  original_text: string;
  sources: {
    ref: Source;
    text: string;
    title?: string;
    source_url?: string;
    source_title?: string;
  }[];
  scope: Scope;
  expires_at: string;
  expected_effect: "unsent_draft";
  ai_provenance: true;
}
export interface Review {
  id: string;
  draft_id: string;
  decision: "accept" | "edit" | "reject";
  exact_digest: string;
  expires_at: string;
  revision: string;
}
export interface SessionContext {
  id: string;
  revision: string;
  subject_id: string | null;
}

export interface KnowledgeEntry {
  source: Source;
  title: string;
  text: string;
  source_url: string;
  source_title: string;
  locale: Locale;
}
export interface KnowledgeResults {
  catalog_digest: string;
  entries: KnowledgeEntry[];
  notice: "synthetic_demo_information";
}
