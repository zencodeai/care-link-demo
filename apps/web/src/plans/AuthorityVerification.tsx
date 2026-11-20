import { useEffect, useRef, useState } from "react";
import {
  authorizationUrl,
  configuredOrigin,
  decodeCeremony,
  decodeProof,
  decodeSession,
  request,
  type Ceremony,
} from "../trust/api";
import { send, type Locale } from "./api";
import { textFor } from "./messages";
import type { PlansChannel } from "./usePlans";
export function AuthorityVerification({
  channel,
  locale,
  onVerified,
}: {
  channel: PlansChannel;
  locale: Locale;
  onVerified: (id: string | null) => void;
}) {
  const text = textFor(locale);
  const [ceremony, setCeremony] = useState<Ceremony | null>(null);
  const popup = useRef<Window | null>(null);
  const subject = channel.session?.subject_id;
  const trackPending = channel.trackPendingVerification;
  useEffect(() => {
    if (channel.review && !channel.review.enabled) {
      setCeremony(null);
      onVerified(null);
      trackPending(null, null);
    }
  }, [channel.review?.enabled]);
  useEffect(() => {
    setCeremony(null);
    onVerified(null);
    trackPending(null, null);
    return () => {
      trackPending(null, null);
      onVerified(null);
    };
  }, [
    subject,
    channel.account?.account_id,
    channel.account?.role,
    trackPending,
  ]);
  useEffect(() => {
    if (!ceremony || ceremony.state === "expired") return;
    const timer = window.setTimeout(
      () => {
        setCeremony({ ...ceremony, state: "expired" });
        trackPending(null, null);
        onVerified(null);
      },
      Math.max(
        0,
        Math.min(Date.parse(ceremony.expires_at) - Date.now(), 2147483647),
      ),
    );
    return () => window.clearTimeout(timer);
  }, [ceremony]);
  const start = () => {
    if (!subject || !channel.account) return;
    if (channel.review) {
      void channel.run(async (signal) => {
        const result = await channel.review!.verify(
          subject,
          channel.account!.revision,
          signal,
          channel.reviewWork()!,
        );
        channel.adoptReviewView(result.view_id);
        await channel.refreshCurrent(signal);
        if (signal.aborted) return;
        setCeremony(result.ceremony);
        onVerified(result.ceremony.ceremony_id);
      });
      return;
    }
    const provider = configuredOrigin(import.meta.env.VITE_OIDC_ORIGIN);
    if (!provider) return;
    void channel.run(async (signal) => {
      // run invokes accepted work synchronously, retaining the trusted click
      // stack. A refused run must not create an orphan blank window.
      const opened = window.open(
        "about:blank",
        "care-link-plan-verification",
        "popup,width=650,height=800",
      );
      if (!opened) return;
      popup.current = opened;
      const closeOpened = () => {
        if (popup.current === opened) popup.current = null;
        try {
          opened.close();
        } catch {
          // A window already closed by its user needs no further cleanup.
        }
      };
      try {
        const value = decodeCeremony(
          JSON.stringify(
            await send(
              {
                key: crypto.randomUUID(),
                path: "/v1/auth/step-up",
                input: "StepUpStart",
                output: "Ceremony",
                body: {
                  purpose: "plan_edit",
                  resource_id: subject,
                  expected_revision: channel.account?.revision,
                },
              },
              signal,
              () => {},
            ),
          ),
        );
        const destination = value.authorization_url
          ? authorizationUrl(value.authorization_url, provider)
          : null;
        setCeremony(value);
        trackPending(subject, value);
        onVerified(null);
        if (!destination) {
          closeOpened();
          return;
        }
        opened.opener = null;
        opened.location.href = destination;
      } catch (error) {
        closeOpened();
        throw error;
      }
    });
  };
  const confirm = () => {
    if (!ceremony) return;
    void channel.run(async (signal) => {
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
      const value = decodeCeremony(
        JSON.stringify(
          await send(
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
            () => {},
          ),
        ),
      );
      setCeremony(value);
      trackPending(subject ?? null, value);
      onVerified(value.state === "verified" ? value.ceremony_id : null);
      if (value.state === "verified") popup.current?.close();
    });
  };
  return (
    <div>
      <p>
        {channel.review
          ? locale === "fr-CA"
            ? "Vérification simulée pour cet examen synthétique. Vous devrez ensuite examiner et confirmer le partage."
            : "Simulated verification for this synthetic review. You will still review and confirm the sharing."
          : text.verificationHint}
      </p>
      <button
        type="button"
        disabled={
          channel.busy ||
          !subject ||
          (!channel.review &&
            !configuredOrigin(import.meta.env.VITE_OIDC_ORIGIN))
        }
        onClick={start}
      >
        {text.beginVerification}
      </button>
      {ceremony && (
        <>
          <p role="status">
            {ceremony.state === "verified"
              ? text.authorityVerified
              : ceremony.state === "expired"
                ? text.expiredPermission
                : text.provider}
          </p>
          {ceremony.state !== "verified" && ceremony.state !== "expired" && (
            <button type="button" disabled={channel.busy} onClick={confirm}>
              {text.confirmVerification}
            </button>
          )}
        </>
      )}
    </div>
  );
}
