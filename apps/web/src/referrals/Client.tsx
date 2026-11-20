import { useEffect, useRef, useState } from "react";
import { read, write, identifierPattern } from "./api";
import { Payload } from "./Payload";
import {
  authorizationUrl,
  configuredOrigin,
  decodeCeremony,
  decodeProof,
  decodeSession,
  request,
  RequestFailure,
  type Ceremony,
} from "../trust/api";
import { useCommand } from "./useCommand";
import type { Actions } from "./useActions";
import { label, type Text } from "./messages";
import type { Consent, DirectoryEntry, Referral } from "./types";
interface Preview {
  expected_revision: string;
  subject_id: string;
  session_id: string;
  purpose: "referral";
  recipient: {
    kind: "service";
    service_id: string;
    directory_revision: string;
  };
  fields: string[];
  basis: "self";
  authority_proof_id: string;
  effective_at: string;
  expires_at: string;
}
export function Client({ actions, text }: { actions: Actions; text: Text }) {
  const [id, setId] = useState("");
  const [referral, setReferral] = useState<Referral | null>(null);
  const [service, setService] = useState<DirectoryEntry | null>(null);
  const [fields, setFields] = useState<string[]>([]);
  const [expires, setExpires] = useState(() =>
    new Date(Date.now() + 600000).toISOString(),
  );
  const [ceremony, setCeremony] = useState<Ceremony | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [grant, setGrant] = useState<Consent | null>(null);
  const commands = useCommand(actions);
  const popup = useRef<Window | null>(null);
  const verifiedSubject = useRef<string | null>(null);
  const provider = configuredOrigin(import.meta.env.VITE_OIDC_ORIGIN);
  const disabled = actions.busy || !actions.session;
  const visible = actions.notice === "done" && !actions.busy;
  useEffect(() => () => popup.current?.close(), []);
  useEffect(() => {
    setReferral(null);
    setService(null);
    setPreview(null);
    setGrant(null);
    popup.current?.close();
  }, [actions.failureEpoch]);
  useEffect(() => {
    if (!ceremony) return;
    const timer = setTimeout(
      () => {
        setCeremony(null);
        setPreview(null);
      },
      Math.max(
        0,
        Math.min(Date.parse(ceremony.expires_at) - Date.now(), 2147483647),
      ),
    );
    return () => clearTimeout(timer);
  }, [ceremony]);
  const clearPreview = () => setPreview(null);
  return (
    <section aria-labelledby="client-consent-title">
      <h2 id="client-consent-title">{text.client}</h2>
      <p>{text.consentHint}</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void actions.run(async (signal) => {
            const value = await read(
              `/v1/referrals/${id}`,
              "ReferralView",
              signal,
            );
            const recipient = await read(
              `/v1/directory/${value.payload.recipient_service_id}`,
              "DirectoryView",
              signal,
            );
            setReferral(value);
            setService(recipient);
            setFields((old) =>
              old.filter((field) =>
                value.payload.fields.some((item) => item.field === field),
              ),
            );
            setPreview(null);
            if (verifiedSubject.current !== value.payload.subject_id)
              setCeremony(null);
            verifiedSubject.current = value.payload.subject_id;
          });
        }}
      >
        <label htmlFor="client-referral">{text.open}</label>
        <input
          id="client-referral"
          value={id}
          onChange={(event) => setId(event.target.value)}
          required
          pattern={identifierPattern}
          disabled={disabled}
        />
        <button disabled={disabled}>{text.openReferral}</button>
      </form>
      {visible && referral && service && (
        <>
          <Payload payload={referral.payload} text={text} />
          <p>
            {service.facts.name} · {service.facts.police_involvement} ·{" "}
            {service.state}
          </p>
          <p className="referral-digest">
            {text.digest}: {referral.digest}
          </p>
          <fieldset disabled={disabled || !!preview}>
            <legend>{text.selected}</legend>
            {[
              ...new Set(referral.payload.fields.map((field) => field.field)),
            ].map((field) => (
              <label key={field}>
                <input
                  type="checkbox"
                  checked={fields.includes(field)}
                  onChange={(event) => {
                    setFields((old) =>
                      event.target.checked
                        ? [...old, field]
                        : old.filter((value) => value !== field),
                    );
                    clearPreview();
                  }}
                />
                {label(field, text)}
              </label>
            ))}
          </fieldset>
          <label htmlFor="client-consent-expiry">{text.consentExpiry}</label>
          <input
            id="client-consent-expiry"
            value={expires}
            disabled={disabled || !!preview}
            onChange={(event) => {
              setExpires(event.target.value);
              clearPreview();
            }}
          />
          {!provider && <p>{text.providerMissing}</p>}
          <button
            disabled={
              disabled ||
              !provider ||
              actions.session?.role !== "pid" ||
              !!preview
            }
            onClick={() => {
              if (!provider || !actions.session || actions.busy) return;
              const opened = window.open(
                "about:blank",
                "care-link-referral-verification",
                "popup,width=650,height=800",
              );
              if (!opened) return;
              popup.current = opened;
              void actions.run(async (signal) => {
                try {
                  const account = decodeSession(
                    await request("", "/v1/auth/session", signal),
                  );
                  const result = decodeCeremony(
                    JSON.stringify(
                      await write(
                        {
                          key: crypto.randomUUID(),
                          path: "/v1/auth/step-up",
                          input: "StepUpStart",
                          output: "Ceremony",
                          body: {
                            purpose: "referral_consent",
                            resource_id: referral.payload.subject_id,
                            expected_revision: account.revision,
                          },
                        },
                        signal,
                      ),
                    ),
                  );
                  setCeremony(result);
                  setPreview(null);
                  if (result.authorization_url) {
                    opened.opener = null;
                    opened.location.href = authorizationUrl(
                      result.authorization_url,
                      provider,
                    );
                  } else opened.close();
                } catch (error) {
                  opened.close();
                  throw error;
                }
              });
            }}
          >
            {text.beginVerification}
          </button>
          {ceremony && (
            <>
              <p role="status">
                {ceremony.state === "verified"
                  ? text.verifiedAuthority
                  : text.provider}
              </p>
              {ceremony.state !== "verified" && (
                <button
                  disabled={disabled}
                  onClick={() =>
                    void actions.run(async (signal) => {
                      const account = decodeSession(
                        await request("", "/v1/auth/session", signal),
                      );
                      const proof = decodeProof(
                        await request(
                          "",
                          `/v1/auth/step-up/proof?ceremony_id=${ceremony.ceremony_id}`,
                          signal,
                        ),
                      );
                      const result = decodeCeremony(
                        JSON.stringify(
                          await write(
                            {
                              key: crypto.randomUUID(),
                              path: "/v1/auth/step-up/confirm",
                              input: "CeremonyConfirm",
                              output: "Ceremony",
                              body: {
                                ceremony_id: ceremony.ceremony_id,
                                proof_intent_id: proof,
                                expected_revision: account.revision,
                              },
                            },
                            signal,
                          ),
                        ),
                      );
                      setCeremony(result);
                      if (result.state === "verified") popup.current?.close();
                    })
                  }
                >
                  {text.confirmVerification}
                </button>
              )}
            </>
          )}
          <button
            disabled={
              disabled ||
              !fields.length ||
              ceremony?.state !== "verified" ||
              !!commands.pending
            }
            onClick={() =>
              void actions.run(async (signal) => {
                if (
                  !ceremony ||
                  Date.parse(ceremony.expires_at) <= Date.now() ||
                  !Number.isFinite(Date.parse(expires)) ||
                  Date.parse(expires) <= Date.now() ||
                  Date.parse(expires) > Date.now() + 900000
                )
                  throw new RequestFailure("rejected");
                const current = await read(
                  `/v1/sessions/${referral.payload.session_id}`,
                  "SessionView",
                  signal,
                );
                setPreview({
                  expected_revision: current.revision,
                  subject_id: referral.payload.subject_id,
                  session_id: referral.payload.session_id,
                  purpose: "referral",
                  recipient: {
                    kind: "service",
                    service_id: service.id,
                    directory_revision: service.revision,
                  },
                  fields: [...fields].sort(),
                  basis: "self",
                  authority_proof_id: ceremony.ceremony_id,
                  effective_at: new Date().toISOString(),
                  expires_at: new Date(expires).toISOString(),
                });
              })
            }
          >
            {text.previewConsent}
          </button>
          {preview && (
            <div>
              <h3>{text.previewConsent}</h3>
              <dl>
                <dt>{text.recipient}</dt>
                <dd>{preview.recipient.service_id}</dd>
                <dt>{text.purpose}</dt>
                <dd>{label(preview.purpose, text)}</dd>
                <dt>{text.selected}</dt>
                <dd>
                  {preview.fields.map((field) => label(field, text)).join(", ")}
                </dd>
                <dt>{text.expiry}</dt>
                <dd>{preview.expires_at}</dd>
              </dl>
              <button
                disabled={disabled || !!commands.pending}
                onClick={() => {
                  commands.send(
                    {
                      path: "/v1/consents",
                      input: "ConsentGrant",
                      output: "ConsentView",
                      body: preview,
                    },
                    (result) => {
                      setGrant(result as Consent);
                      setPreview(null);
                    },
                  );
                }}
              >
                {text.grantConsent}
              </button>
              <button
                disabled={disabled || !!commands.pending}
                onClick={() => setPreview(null)}
              >
                {text.cancelConsent}
              </button>
            </div>
          )}
        </>
      )}
      {visible && grant && (
        <div>
          <p>{text.grantRecorded}</p>
          <p className="referral-digest">{grant.id}</p>
          <p>
            {text.expiry}: {grant.expires_at}
          </p>
          <p>
            {text.revoked}: {grant.revoked_at ?? "—"}
          </p>
          <button
            disabled={disabled || !!grant.revoked_at || !!commands.pending}
            onClick={() => {
              commands.send(
                {
                  path: `/v1/consents/${grant.id}/revoke`,
                  input: "RevisionCommand",
                  output: "CommandResult",
                  body: { expected_revision: grant.revision },
                },
                async (_result, signal) => {
                  setGrant(
                    await read(
                      `/v1/consents/${grant.id}`,
                      "ConsentView",
                      signal,
                    ),
                  );
                },
              );
            }}
          >
            {text.revokeConsent}
          </button>
        </div>
      )}
      {commands.pending && !actions.busy && (
        <p className="referral-digest" role="status">
          {text.unknown} {commands.pending.key}
          <button disabled={disabled} onClick={commands.retry}>
            {text.resume}
          </button>
        </p>
      )}
    </section>
  );
}
