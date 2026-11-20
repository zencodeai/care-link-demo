import type { Session } from "../trust/api";
import type { Workspace as ExistingWorkspace } from "../review/types";
import type { PlansSelection } from "../plans/review";
export interface PlansReviewContext {
  enabled: true;
  mode: "plans";
  authentication_mode: "automatic_review";
  environment: "synthetic-review";
  origin: string;
  run_state: "active" | "closing" | "closed";
  run_id: string;
  slot_id: "pid" | "carer" | "professional" | "worker1";
  account_id: string;
  role: Session["role"];
  started_at: string;
  expires_at: string;
}
export interface PlanDraft {
  id: string;
  session_id: string;
  kind: "plan";
  revision: string;
  text: string;
  expires_at: string;
}
export type PlansWorkspaceData = Omit<ExistingWorkspace, "drafts"> & {
  drafts: (ExistingWorkspace["drafts"][number] | PlanDraft)[];
};
export interface PlansReviewWorkspace {
  workspace: PlansWorkspaceData;
  selection: PlansSelection;
  expires_at: string;
}
export interface ReviewSession extends Session {
  review_run_id?: string;
  review_slot_id?: string;
  review_origin?: string;
}
export interface ViewLease {
  view_id: string;
  state: "active" | "observer";
  revision: string;
}
