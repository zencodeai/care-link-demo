import { useState, type Dispatch, type SetStateAction } from "react";
import type { Ceremony, Session } from "../trust/api";
import { planFields, type PlanField } from "./api";

export interface PlanFormState {
  version: "plans-review.form.v1";
  planField: PlanField;
  planWords: string;
  planUnknown: boolean;
  planSafety: boolean;
  reportWords: string;
  recipient: string;
  fields: PlanField[];
  expires: string;
  grantId: string;
}
export function emptyPlanForm(recipient = ""): PlanFormState {
  return {
    version: "plans-review.form.v1",
    planField: "plan.warning_signs",
    planWords: "",
    planUnknown: false,
    planSafety: false,
    reportWords: "",
    recipient,
    fields: [],
    expires: new Date(Date.now() + 3600000).toISOString().slice(0, 16),
    grantId: "",
  };
}
export function decodePlanForm(text: string): PlanFormState {
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid review draft");
  const row = value as Record<string, unknown>;
  if (
    Object.keys(row).length !== 10 ||
    row.version !== "plans-review.form.v1" ||
    !planFields.includes(row.planField as PlanField) ||
    typeof row.planWords !== "string" ||
    row.planWords.length > 2000 ||
    typeof row.reportWords !== "string" ||
    row.reportWords.length > 2000 ||
    typeof row.planUnknown !== "boolean" ||
    typeof row.planSafety !== "boolean" ||
    typeof row.recipient !== "string" ||
    row.recipient.length > 36 ||
    typeof row.grantId !== "string" ||
    row.grantId.length > 36 ||
    typeof row.expires !== "string" ||
    row.expires.length > 32 ||
    !Array.isArray(row.fields) ||
    row.fields.length > planFields.length ||
    !row.fields.every((field: unknown) =>
      planFields.includes(field as PlanField),
    )
  )
    throw new Error("Invalid review draft");
  return row as unknown as PlanFormState;
}
export interface PlanDraftBridge {
  value: PlanFormState;
  edit: <K extends keyof PlanFormState>(
    key: K,
    value: PlanFormState[K],
  ) => void;
}
export function usePlanFormField<K extends keyof PlanFormState>(
  bridge: PlanDraftBridge | undefined,
  key: K,
  initial: PlanFormState[K],
): [PlanFormState[K], Dispatch<SetStateAction<PlanFormState[K]>>] {
  const [local, setLocal] = useState(initial);
  const current = bridge ? bridge.value[key] : local;
  const edit: Dispatch<SetStateAction<PlanFormState[K]>> = (next) => {
    const value = typeof next === "function" ? next(current) : next;
    if (bridge) bridge.edit(key, value);
    else setLocal(value);
  };
  return [current, edit];
}
export interface ReviewWorkLease {
  readonly token: symbol;
  readonly view_id: string;
  release: () => void;
}
export interface PlansReviewActions {
  account_id: string;
  role: Session["role"];
  expires_at: string;
  enabled: boolean;
  enter: (signal: AbortSignal) => Promise<ReviewWorkLease>;
  renew: (signal: AbortSignal, work?: ReviewWorkLease) => Promise<string>;
  verify: (
    subject: string,
    revision: string,
    signal: AbortSignal,
    work: ReviewWorkLease,
  ) => Promise<{ ceremony: Ceremony; view_id: string }>;
}
export interface PlansSelection {
  session_id: string;
  plan_id: string | null;
  recipient_id: string | null;
}
