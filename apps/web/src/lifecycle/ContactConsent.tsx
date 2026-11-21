import { useEffect, useState } from "react";
import type { Consent } from "../plans/api";
import { Field } from "./Fields";
import { Verification } from "./Verification";
import { utc } from "./api";
import type { Text } from "./messages";
import type { SessionContext } from "./types";
import type { Channel } from "./useLifecycle";
interface Preview {
  recipient: string;
  expires: string;
  proof: string;
  revision: string;
  effective: string;
}
export function ContactConsent({
  channel,
  text,
  session,
  onGrant,
}: {
  channel: Channel;
  text: Text;
  session: SessionContext;
  onGrant: (grant: string, recipient: string) => void;
}) {
  const [recipient, setRecipient] = useState(channel.account?.account_id ?? "");
  const [expires, setExpires] = useState("");
  const [proof, setProof] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [grant, setGrant] = useState<Consent | null>(null);
  const [withdrawn, setWithdrawn] = useState(false);
  useEffect(() => {
    setGrant(null);
    setProof(null);
    setPreview(null);
  }, [channel.privateEpoch]);
  if (channel.account?.role !== "pid" || !session.subject_id) return null;
  return (
    <div>
      <h3>{text.contactTitle}</h3>
      <Verification
        channel={channel}
        text={text}
        subject={session.subject_id}
        purpose="follow_up_consent"
        contact
        onVerified={setProof}
      />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (proof)
            setPreview({
              recipient,
              expires: utc(expires),
              proof,
              revision: session.revision,
              effective: new Date().toISOString(),
            });
        }}
      >
        <Field
          id="contact-recipient"
          label={text.recipient}
          value={recipient}
          onChange={(value) => {
            setRecipient(value);
            setPreview(null);
          }}
          identifier
        />
        <Field
          id="contact-expiry"
          label={text.contactExpiry}
          value={expires}
          onChange={(value) => {
            setExpires(value);
            setPreview(null);
          }}
          type="datetime-local"
        />
        <p>{text.contactFields}</p>
        <button disabled={channel.disabled || !proof}>
          {text.previewContact}
        </button>
      </form>
      {preview && (
        <div>
          <p>
            {text.subject}: {session.subject_id}
          </p>
          <p>
            {text.recipient}: {preview.recipient}
          </p>
          <p>{text.contactFields}</p>
          <p>
            {text.contactExpiry}:{" "}
            <time dateTime={preview.expires}>{preview.expires}</time>
          </p>
          <button
            disabled={
              channel.disabled ||
              proof !== preview.proof ||
              session.revision !== preview.revision
            }
            onClick={() =>
              channel.command(
                {
                  path: "/v1/consents",
                  input: "ConsentGrant",
                  output: "ConsentView",
                  body: {
                    expected_revision: preview.revision,
                    subject_id: session.subject_id,
                    session_id: session.id,
                    purpose: "follow_up",
                    recipient: {
                      kind: "account",
                      account_id: preview.recipient,
                    },
                    fields: ["summary", "outcome"],
                    basis: "self",
                    authority_proof_id: preview.proof,
                    effective_at: preview.effective,
                    expires_at: preview.expires,
                  },
                },
                (value) => {
                  setGrant(value);
                  setPreview(null);
                  setWithdrawn(false);
                  onGrant(value.id, preview.recipient);
                },
              )
            }
          >
            {text.confirmContact}
          </button>
        </div>
      )}
      {grant && (
        <div>
          <p>
            {text.grant}: {grant.id}
          </p>
          <button
            disabled={channel.disabled || withdrawn}
            onClick={() =>
              channel.command(
                {
                  path: `/v1/consents/${grant.id}/revoke`,
                  input: "RevisionCommand",
                  output: "CommandResult",
                  body: { expected_revision: grant.revision },
                },
                () => {
                  setWithdrawn(true);
                  onGrant("", recipient);
                },
              )
            }
          >
            {text.revokeContact}
          </button>
        </div>
      )}
      {withdrawn && <p role="status">{text.contactWithdrawn}</p>}
    </div>
  );
}
