import { useEffect, useRef, useState } from "react";
import {
  authorizationUrl,
  configuredOrigin,
  decodeProof,
  request,
  RequestFailure,
  type Ceremony,
} from "../trust/api";
import { write } from "./api";
import type { Text } from "./messages";
import type { Channel } from "./useLifecycle";
export function Verification({
  channel,
  text,
  subject,
  purpose,
  onVerified,
  contact = false,
}: {
  channel: Channel;
  text: Text;
  subject: string;
  purpose: "export" | "delete" | "follow_up_consent";
  contact?: boolean;
  onVerified: (ceremony: string | null) => void;
}) {
  const [ceremony, setCeremony] = useState<Ceremony | null>(null);
  const [now, setNow] = useState(Date.now());
  const [popupBlocked, setPopupBlocked] = useState(false);
  const popup = useRef<Window | null>(null);
  const provider = configuredOrigin(import.meta.env.VITE_OIDC_ORIGIN);
  useEffect(() => {
    setCeremony(null);
    onVerified(null);
  }, [subject, purpose, channel.epoch, channel.privateEpoch]);
  useEffect(() => {
    if (!ceremony) return;
    const timer = setInterval(() => {
      const current = Date.now();
      setNow(current);
      if (current >= Date.parse(ceremony.expires_at)) {
        setCeremony(null);
        onVerified(null);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [ceremony, onVerified]);
  useEffect(() => () => popup.current?.close(), []);
  const cooling = ceremony?.state === "cooling_off";
  const canRestart = !cooling || now >= Date.parse(ceremony.not_before);
  function start() {
    if (!provider) return;
    // Open from the click stack; current authority is checked before starting a ceremony.
    const opened = window.open(
      "about:blank",
      "care-link-rights-verification",
      "popup,width=650,height=800",
    );
    if (!opened) {
      setPopupBlocked(true);
      return;
    }
    popup.current = opened;
    setPopupBlocked(false);
    void channel.run(async (signal, actor) => {
      try {
        const result = await write(
          {
            key: crypto.randomUUID(),
            path: "/v1/auth/step-up",
            input: "StepUpStart",
            output: "Ceremony",
            body: {
              purpose,
              resource_id: subject,
              expected_revision: actor.revision,
            },
          },
          signal,
          () => {},
        );
        if (!result.authorization_url) throw new RequestFailure("invalid");
        opened.opener = null;
        opened.location.href = authorizationUrl(
          result.authorization_url,
          provider,
        );
        setCeremony(result);
        onVerified(null);
      } catch (error) {
        opened.close();
        throw error;
      }
    });
  }
  function confirm() {
    if (!ceremony) return;
    void channel.run(async (signal, actor) => {
      const proof = decodeProof(
        await request(
          "",
          `/v1/auth/step-up/proof?ceremony_id=${ceremony.ceremony_id}`,
          signal,
        ),
      );
      const value = await write(
        {
          key: crypto.randomUUID(),
          path: "/v1/auth/step-up/confirm",
          input: "CeremonyConfirm",
          output: "Ceremony",
          body: {
            ceremony_id: ceremony.ceremony_id,
            proof_intent_id: proof,
            expected_revision: actor.revision,
          },
        },
        signal,
        () => {},
      );
      setCeremony(value);
      onVerified(value.state === "verified" ? value.ceremony_id : null);
      popup.current?.close();
    });
  }
  return (
    <div>
      <h3>{text.verification}</h3>
      <p>{contact ? text.contactHint : text.verificationHint}</p>
      {!provider && <p>{text.providerMissing}</p>}
      {popupBlocked && <p role="alert">{text.popupBlocked}</p>}
      <button
        type="button"
        disabled={
          channel.disabled ||
          !provider ||
          !subject ||
          !canRestart ||
          ceremony?.state === "verified"
        }
        onClick={start}
      >
        {cooling ? text.second : text.begin}
      </button>
      {ceremony && (
        <div>
          {cooling && (
            <p role="status">
              {text.cooling}:{" "}
              <time dateTime={ceremony.not_before}>{ceremony.not_before}</time>
            </p>
          )}
          {ceremony.state === "verified" ? (
            <p role="status">{text.verified}</p>
          ) : (
            <button
              type="button"
              disabled={
                channel.disabled ||
                (cooling && now < Date.parse(ceremony.not_before))
              }
              onClick={confirm}
            >
              {text.confirm}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
