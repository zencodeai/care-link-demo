import { useEffect, useState } from "react";
import {
  planFields,
  uuid,
  valueText,
  type Locale,
  type PlanField,
  type Assertion,
} from "./api";
import { AuthorityVerification } from "./AuthorityVerification";
import { fieldLabels, textFor } from "./messages";
import type { PlansChannel } from "./usePlans";
import { usePlanFormField, type PlanDraftBridge } from "./review";
interface Preview {
  recipient: string;
  expires: string;
  effective: string;
  fields: PlanField[];
  subject: string;
  session: string;
  revision: string;
  proof: string;
  planId: string;
  planRevision: string;
  values: Assertion[];
}
export function ConsentPanel({
  channel,
  locale,
  draft,
}: {
  channel: PlansChannel;
  locale: Locale;
  draft?: PlanDraftBridge | undefined;
}) {
  const text = textFor(locale),
    labels = fieldLabels[locale];
  const [recipient, setRecipient] = usePlanFormField(draft, "recipient", "");
  const [expires, setExpires] = usePlanFormField(
    draft,
    "expires",
    new Date(Date.now() + 3600000).toISOString().slice(0, 16),
  );
  const [fields, setFields] = usePlanFormField(draft, "fields", []);
  const [proof, setProof] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [grantId, setGrantId] = usePlanFormField(draft, "grantId", "");
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    if (channel.review && !channel.review.enabled) {
      setProof(null);
      setPreview(null);
    }
  }, [channel.review?.enabled]);
  const disabled = channel.busy || !!channel.pending;
  const grant = channel.grant;
  const session = channel.session;
  const ownPlan =
    channel.currentPlan?.subject_id === session?.subject_id
      ? channel.currentPlan
      : null;
  const eligible = channel.account?.role === "pid" && !!session?.subject_id;
  const revokeAllowed =
    grant &&
    grant.grantor_id === channel.account?.account_id &&
    !grant.revoked_at;
  function prepare() {
    if (
      !uuid.test(recipient) ||
      !fields.length ||
      !proof ||
      !session?.subject_id ||
      !ownPlan ||
      !Number.isFinite(Date.parse(expires + "Z")) ||
      Date.parse(expires + "Z") <= Date.now()
    ) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setPreview({
      recipient,
      expires: new Date(expires + "Z").toISOString(),
      effective: new Date().toISOString(),
      fields: [...fields],
      subject: session.subject_id,
      session: session.id,
      revision: session.revision,
      proof,
      planId: ownPlan.id,
      planRevision: ownPlan.revision,
      values: ownPlan.fields.filter((item) =>
        fields.some((field) => field === item.field),
      ),
    });
  }
  return (
    <section aria-labelledby="sharing-title">
      <h3 id="sharing-title">{text.consent}</h3>
      <p>{text.sharingHint}</p>
      {eligible && (
        <>
          <AuthorityVerification
            channel={channel}
            locale={locale}
            onVerified={setProof}
          />
          <form
            onSubmit={(event) => {
              event.preventDefault();
              prepare();
            }}
          >
            {channel.review ? (
              <p>
                {locale === "fr-CA"
                  ? "Destinataire désigné pour cet examen"
                  : "Designated recipient for this review"}
              </p>
            ) : (
              <label htmlFor="share-recipient">{text.recipient}</label>
            )}
            <input
              id="share-recipient"
              aria-label={text.recipient}
              hidden={!!channel.review}
              value={recipient}
              autoComplete="off"
              disabled={disabled}
              onChange={(event) => {
                setRecipient(event.target.value);
                setPreview(null);
              }}
            />
            <label htmlFor="share-expiry">{text.expires}</label>
            <input
              id="share-expiry"
              type="datetime-local"
              value={expires}
              disabled={disabled}
              onChange={(event) => {
                setExpires(event.target.value);
                setPreview(null);
              }}
            />
            <fieldset disabled={disabled}>
              <legend>{text.selected}</legend>
              {planFields.map((field) => (
                <label key={field}>
                  <input
                    type="checkbox"
                    checked={fields.includes(field)}
                    onChange={(event) => {
                      setFields((previous) =>
                        event.target.checked
                          ? [...previous, field]
                          : previous.filter((item) => item !== field),
                      );
                      setPreview(null);
                    }}
                  />
                  {labels[field]}
                </label>
              ))}
            </fieldset>
            <button type="submit" disabled={disabled || !proof || !ownPlan}>
              {text.preview}
            </button>
          </form>
          {invalid && <p role="alert">{text.invalid}</p>}
          {preview && (
            <div className="notice">
              <h4>{text.preview}</h4>
              <p>{text.purpose}</p>
              <p>
                {text.recipient}: <code>{preview.recipient}</code>
              </p>
              <p>
                {text.selected}:{" "}
                {preview.fields.map((field) => labels[field]).join(", ")}
              </p>
              <ul>
                {preview.values.map((item) => (
                  <li key={item.id}>
                    {item.field}: {valueText(item.value)}
                    <p>
                      {text.author}: <code>{item.author_id}</code> ·{" "}
                      {text.verification}: {item.verification}
                    </p>
                    <p>
                      {item.source
                        ? `${text.source}: ${item.source.id} · ${text.revision}: ${item.source.revision} · ${item.source.verification}`
                        : text.noSource}
                    </p>
                  </li>
                ))}
              </ul>
              <p>
                {text.consentTime}:{" "}
                <time dateTime={preview.effective}>{preview.effective}</time>
              </p>
              <p>
                {text.expires}:{" "}
                <time dateTime={preview.expires}>{preview.expires}</time>
              </p>
              <button
                type="button"
                disabled={
                  disabled ||
                  !proof ||
                  proof !== preview.proof ||
                  session?.id !== preview.session ||
                  session?.subject_id !== preview.subject ||
                  session.revision !== preview.revision ||
                  ownPlan?.id !== preview.planId ||
                  ownPlan.revision !== preview.planRevision
                }
                onClick={() => {
                  channel.command(
                    "/v1/consents",
                    "ConsentGrant",
                    "ConsentView",
                    {
                      expected_revision: preview.revision,
                      subject_id: preview.subject,
                      session_id: preview.session,
                      purpose: "plan",
                      recipient: {
                        kind: "account",
                        account_id: preview.recipient,
                      },
                      fields: preview.fields,
                      basis: "self",
                      authority_proof_id: preview.proof,
                      effective_at: preview.effective,
                      expires_at: preview.expires,
                    },
                  );
                  setPreview(null);
                }}
              >
                {text.grant}
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => setPreview(null)}
              >
                {text.cancel}
              </button>
            </div>
          )}
        </>
      )}
      <form
        hidden={!!channel.review}
        onSubmit={(event) => {
          event.preventDefault();
          if (!uuid.test(grantId)) {
            setInvalid(true);
            return;
          }
          setInvalid(false);
          void channel.loadGrant(grantId);
        }}
      >
        <label htmlFor="share-id">{text.grantId}</label>
        <input
          id="share-id"
          value={grantId}
          onChange={(event) => setGrantId(event.target.value)}
          autoComplete="off"
        />
        <button type="submit" disabled={disabled}>
          {text.loadConsent}
        </button>
      </form>
      {grant && (
        <div>
          <p>
            {text.grantId}: <code>{grant.id}</code> · {text.revision}:{" "}
            {grant.revision}
          </p>
          <p>
            {text.status}:{" "}
            {grant.revoked_at
              ? text.revoked
              : Date.parse(grant.expires_at) <= Date.now() ||
                  Date.parse(grant.effective_at) > Date.now()
                ? text.expiredPermission
                : text.ready}
          </p>
          <p>
            {text.purpose}: {grant.scope.purpose}
          </p>
          <p>
            {text.recipient}: <code>{grant.scope.recipient_id}</code>
          </p>
          <p>
            {text.selected}:{" "}
            {grant.scope.fields
              .map((field) =>
                planFields.find((item) => item === field)
                  ? labels[
                      planFields.find((item) => item === field) ??
                        "plan.warning_signs"
                    ]
                  : field,
              )
              .join(", ")}
          </p>
          <p>
            {text.consentTime}:{" "}
            <time dateTime={grant.effective_at}>{grant.effective_at}</time>
          </p>
          <p>
            {text.expires}:{" "}
            <time dateTime={grant.expires_at}>{grant.expires_at}</time>
          </p>
          <p>
            {text.digest}: <code>{grant.scope_digest}</code>
          </p>
          {revokeAllowed && (
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                channel.command(
                  `/v1/consents/${grant.id}/revoke`,
                  "RevisionCommand",
                  "CommandResult",
                  { expected_revision: grant.revision },
                )
              }
            >
              {text.revoke}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
