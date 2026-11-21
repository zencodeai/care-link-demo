import { usePrivateValue } from "./usePrivateValue";
import { useState } from "react";
import { Field, Select, digestPattern, uuidPattern } from "./Fields";
import { utc } from "./api";
import type { Text } from "./messages";
import type { Receipt } from "./types";
import type { Channel } from "./useGovernance";
import { Choices } from "./Labels";
export function GrantPanel({
  channel,
  text,
}: {
  channel: Channel;
  text: Text;
}) {
  const [grantee, setGrantee] = useState(""),
    [revision, setRevision] = useState(""),
    [approval, setApproval] = useState(""),
    [expiry, setExpiry] = useState(""),
    [session, setSession] = useState(""),
    [subject, setSubject] = useState(""),
    [recipient, setRecipient] = useState(""),
    [field, setField] = useState("");
  const [receipt, setReceipt] = usePrivateValue<Receipt>(channel);
  return (
    <section aria-labelledby="grant-title">
      <h2 id="grant-title">{text.grants}</h2>
      <p>{text.grantHint}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const fields = field ? [field] : [];
          channel.command(
            {
              path: "/v1/access/grants",
              input: "ScopeGrantCreate",
              output: "CommandResult",
              body: {
                expected_revision: revision,
                grantee_id: grantee,
                scope: {
                  session_id: session || null,
                  subject_id: subject || null,
                  purpose: "audit",
                  fields,
                  recipient_id: recipient || null,
                },
                fields,
                expires_at: utc(expiry),
                approval_receipt_id: approval,
              },
            },
            setReceipt,
          );
        }}
      >
        <fieldset disabled={channel.disabled}>
          <Field
            id="grant-grantee"
            label={text.grantee}
            value={grantee}
            onChange={setGrantee}
            pattern={uuidPattern}
          />
          <Field
            id="grant-revision"
            label={text.expected}
            value={revision}
            onChange={setRevision}
            pattern="0|[1-9][0-9]{0,18}"
          />
          <Field
            id="grant-approval"
            label={text.approval}
            value={approval}
            onChange={setApproval}
            pattern={uuidPattern}
          />
          <Field
            id="grant-expiry"
            label={text.grantExpiry}
            value={expiry}
            onChange={setExpiry}
            type="datetime-local"
          />
          <Field
            id="grant-session"
            label={text.session}
            value={session}
            onChange={setSession}
            pattern={uuidPattern}
            required={false}
          />
          <Field
            id="grant-subject"
            label={text.subject}
            value={subject}
            onChange={setSubject}
            pattern={uuidPattern}
            required={false}
          />
          <Field
            id="grant-recipient"
            label={text.recipient}
            value={recipient}
            onChange={setRecipient}
            pattern={uuidPattern}
            required={false}
          />
          <Select
            id="grant-field"
            label={text.field}
            value={field}
            onChange={setField}
          >
            <option value="">{text.noFields}</option>
            <Choices
              values={[
                "summary",
                "outcome",
                "needs",
                "preferences",
                "observations",
                "rationale",
              ]}
              text={text}
            />
          </Select>
          <button>{text.grant}</button>
        </fieldset>
      </form>
      {receipt && (
        <p>
          {text.receipt}: <code>{receipt.resource_id}</code> · {text.revision}:{" "}
          {receipt.revision}
        </p>
      )}
    </section>
  );
}
export function ExceptionPanel({
  channel,
  text,
}: {
  channel: Channel;
  text: Text;
}) {
  const [revision, setRevision] = useState(""),
    [approval, setApproval] = useState(""),
    [expiry, setExpiry] = useState(""),
    [rule, setRule] = useState(""),
    [compensating, setCompensating] = useState(""),
    [session, setSession] = useState(""),
    [subject, setSubject] = useState("");
  const [receipt, setReceipt] = usePrivateValue<Receipt>(channel);
  return (
    <section aria-labelledby="exception-title">
      <h2 id="exception-title">{text.exception}</h2>
      <p>{text.exceptionHint}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          channel.command(
            {
              path: "/v1/exceptions",
              input: "ExceptionCreate",
              output: "CommandResult",
              body: {
                expected_revision: revision,
                scope: {
                  session_id: session || null,
                  subject_id: subject || null,
                  purpose: "governance",
                  fields: [],
                  recipient_id: null,
                },
                policy_rule_id: rule,
                approver_receipt_id: approval,
                expires_at: utc(expiry),
                compensating_control_digest: compensating,
              },
            },
            setReceipt,
          );
        }}
      >
        <fieldset disabled={channel.disabled}>
          <Field
            id="exception-revision"
            label={text.expected}
            value={revision}
            onChange={setRevision}
            pattern="0|[1-9][0-9]{0,18}"
          />
          <Field
            id="exception-rule"
            label={text.rule}
            value={rule}
            onChange={setRule}
          />
          <Field
            id="exception-approval"
            label={text.approval}
            value={approval}
            onChange={setApproval}
            pattern={uuidPattern}
          />
          <Field
            id="exception-compensating"
            label={text.compensating}
            value={compensating}
            onChange={setCompensating}
            pattern={digestPattern}
          />
          <Field
            id="exception-expiry"
            label={text.exceptionExpiry}
            value={expiry}
            onChange={setExpiry}
            type="datetime-local"
          />
          <Field
            id="exception-session"
            label={text.session}
            value={session}
            onChange={setSession}
            pattern={uuidPattern}
            required={false}
          />
          <Field
            id="exception-subject"
            label={text.subject}
            value={subject}
            onChange={setSubject}
            pattern={uuidPattern}
            required={false}
          />
          <button>{text.createException}</button>
        </fieldset>
      </form>
      {receipt && (
        <p>
          {text.receipt}: <code>{receipt.resource_id}</code> · {text.revision}:{" "}
          {receipt.revision}
        </p>
      )}
    </section>
  );
}
