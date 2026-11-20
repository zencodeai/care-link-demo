/** Offline pinned Ajv standalone compilation; never imported by browser code. */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const root = new URL("../", import.meta.url);
const packageRoot = new URL("packages/contracts/typescript/", root);
const require = createRequire(new URL("package.json", packageRoot));
const Ajv2020 = require("ajv/dist/2020.js").default;
const addFormats = require("ajv-formats").default;
const standaloneCode = require("ajv/dist/standalone/index.js").default;
const { _ } = require("ajv/dist/compile/codegen/index.js");
const names = [
  "PlansReviewContext",
  "PlansReviewWorkspace",
  "SessionCreate",
  "PlanCreate",
  "PlanFieldCreate",
  "PlanView",
  "ConsentGrant",
  "ConsentView",
  "DirectoryQuery",
  "DirectoryIngest",
  "DirectoryView",
  "DirectoryPage",
  "OwnReportPage",
  "Gateway_own_reports_read",
  "Gateway_plan_create",
  "Gateway_plan_read",
  "Gateway_plan_field_append",
  "Gateway_plan_retire",
  "Gateway_consent_grant",
  "Gateway_consent_read",
  "Gateway_consent_revoke",
  "Gateway_directory_search",
  "Gateway_directory_read",
  "Gateway_directory_ingest",
  "Gateway_directory_suspend",
  "RevisionCommand",
  "Error",
  "DeveloperCapability",
  "BrowserCsrf",
  "ContinuationRecoveryStart",
  "Gateway_continuation_issue",
  "StepUpProof",
  "HelpCreateIntent",
  "LoginStart",
  "LoginIntent",
  "LoginCallback",
  "BrowserSession",
  "Empty",
  "StepUpStart",
  "Ceremony",
  "CeremonyConfirm",
  "HelpCreate",
  "HelpView",
  "HelpAuthorityRequest",
  "FreshHelpAuthority",
  "Signal",
  "SignalAck",
  "StaticManifest",
  "StaticPublish",
  "CommandResult",
  "SessionView",
  "DisclosureAck",
  "TurnSubmit",
  "AssessmentView",
  "AssertionCreate",
  "AssertionView",
  "ChoiceCommand",
  "HumanRequest",
  "ReasonCommand",
  "QueueView",
  "QueuePage",
  "AssignmentCommand",
  "AssignmentView",
  "TransferPreparation",
  "TransferConfirm",
  "ObserveCommand",
  "MessageSubmit",
  "MessageView",
  "MessagePage",
  "ContinuationRotate",
  "ContinuationIssued",
  "ContinuationRecover",
  "OperationStatus",
  "ControlChange",
  "ChannelChallengeView",
  "ChannelAckSubmit",
  "ChannelAckView",
  "EventView",
  "PolicyInput",
  "PolicyDecision",
  "JournalAppend",
  "JournalHead",
  "JournalRecord",
  "DutyDefinition",
  "DutyEvidence",
  "WorkloadActor",
  "DueJob",
  "Gateway_continuation_rotate",
  "Gateway_continuation_recover",
  "Gateway_operation_status",
  "Gateway_session_create",
  "Gateway_session_read",
  "Gateway_session_disclosure",
  "Gateway_session_turns",
  "Gateway_session_assertions",
  "Gateway_session_choices",
  "Gateway_session_human_request",
  "Gateway_session_end",
  "Gateway_session_events",
  "Gateway_messages_read",
  "Gateway_message_send",
  "Gateway_queue_list",
  "Gateway_workforce_reserve",
  "Gateway_workforce_accept",
  "Gateway_workforce_prepare_transfer",
  "Gateway_workforce_confirm_transfer",
  "Gateway_workforce_transfer_failed",
  "Gateway_workforce_observe",
  "Gateway_workforce_takeover",
  "Gateway_control_change",
  "Gateway_channel_challenge_read",
  "Gateway_channel_ack",
  "MetadataRequest",
  "MetadataResult",
  "IdentityEvidence",
  "SignedDelegation",
  "PageQuery",

  "BackupView",
  "ReviewIntentCancel",
  "Gateway_review_intent_cancel",
  "ReviewWorkspaceQuery",
  "ReviewDraftSave",
  "ReviewIntentPrepare",
  "ReviewDraftView",
  "ReviewIntentView",
  "ReviewHandshakeView",
  "ReviewWorkspace",
  "Gateway_review_workspace",
  "Gateway_review_draft_save",
  "Gateway_review_intent_prepare",
];
// Internal gateway/policy/journal DTOs stay in the shared source snapshot but
// are not shipped as executable browser validators.
const internal = new Set([
  "DutyDefinition",
  "DutyEvidence",
  "WorkloadActor",
  "DueJob",
  "PolicyInput",
  "PolicyDecision",
  "JournalAppend",
  "JournalHead",
  "JournalRecord",
  "DutyDefinition",
  "DutyEvidence",
  "WorkloadActor",
  "DueJob",
  "BackupView",
  "MetadataRequest",
  "MetadataResult",
  "IdentityEvidence",
  "SignedDelegation",
]);
const browserNames = names.filter(
  (name) => !name.startsWith("Gateway_") && !internal.has(name),
);
const raw = readFileSync(new URL("src/schema.json", packageRoot));
const schema = JSON.parse(raw);
const ajv = new Ajv2020({
  strict: true,
  strictTypes: false,
  allErrors: false,
  code: { source: true },
});
addFormats(ajv);
ajv.addKeyword({
  keyword: "x-decimalMaximum",
  type: "string",
  schemaType: "string",
  errors: false,
  code(context) {
    const { data, schema: maximum } = context;
    // Identical canonical decimal semantics, expressed through Ajv CodeGen so
    // standalone output has no runtime closure or Function-constructor fallback.
    context.fail(
      _`typeof ${data} !== "string" || ${data}.length === 0 || /[^0-9]/.test(${data}) || (${data}.length > 1 && ${data}[0] === "0") || ${data}.length > 19 || BigInt(${data}) > BigInt(${maximum})`,
    );
  },
});
ajv.addSchema(schema);
const exports = Object.fromEntries(
  browserNames.map((name) => [name, `${schema.$id}#/$defs/${name}`]),
);
const sourceHash = createHash("sha256").update(raw).digest("hex");
const header = `/* Generated offline by tools/generate_browser_validators.mjs; do not edit.\nSchema SHA256 ${sourceHash}; Ajv ${require("ajv/package.json").version}; ajv-formats ${require("ajv-formats/package.json").version}. */\n`;
const outputs = new Map([
  [
    new URL("src/validators.generated.cjs", packageRoot),
    header + standaloneCode(ajv, exports) + "\n",
  ],
  [
    new URL("src/validators.generated.d.cts", packageRoot),
    header +
      "declare const validators: Record<string, (value: unknown) => boolean>;\nexport = validators;\n",
  ],
]);
const check = process.argv.includes("--check");
if (process.argv.slice(2).some((argument) => argument !== "--check"))
  throw new Error("Only --check is supported");
for (const [target, expected] of outputs) {
  if (check) {
    if (readFileSync(target, "utf8") !== expected)
      throw new Error(`Standalone validator drift: ${fileURLToPath(target)}`);
  } else writeFileSync(target, expected);
}
process.stdout.write(
  `Browser validators ${check ? "match" : "generated from"} the pinned schema (${browserNames.length} public contracts).\n`,
);
